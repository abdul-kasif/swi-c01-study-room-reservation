"""
Additional hard tests for the Study Room Reservation System.

Save as: tests/test_reservation_hard_cases.py

Run:
    pytest -v tests/test_reservation_hard_cases.py

These tests use the existing FastAPI app and SQLite engine. They assume the
application's current public API and the reset_db fixture pattern from co2-test.py.
"""

import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.main import app, Base, engine

os.environ["ADMIN_TOKEN"] = os.getenv("ADMIN_TOKEN")
ADMIN_TOKEN = os.environ["ADMIN_TOKEN"]


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # Seed default resources to satisfy REQ-03
    from src.repository import ResourceModel, SessionLocal

    db = SessionLocal()
    resources = [
        ResourceModel(resource_id="Room1", name="Standard Room 1", is_active=True),
        ResourceModel(resource_id="Room2", name="Standard Room 2", is_active=True),
        ResourceModel(resource_id="Room3", name="Standard Room 3", is_active=True),
        ResourceModel(resource_id="Room4", name="Standard Room 4", is_active=True),
        ResourceModel(resource_id="Room-A", name="Room A", is_active=True),
        ResourceModel(resource_id="Room-B", name="Room B", is_active=True),
        ResourceModel(resource_id="VIP_Room1", name="VIP Room 1", is_active=True),
        ResourceModel(resource_id="VIP_Room2", name="VIP Room 2", is_active=True),
        ResourceModel(resource_id="VIP_Room3", name="VIP Room 3", is_active=True),
        ResourceModel(resource_id="VIP_Room-A", name="VIP Room A", is_active=True),
        ResourceModel(resource_id="VIP_R", name="VIP Room R", is_active=True),
    ]
    db.add_all(resources)
    db.commit()
    db.close()
    yield


client = TestClient(app)


@pytest.fixture
def future_slot():
    """A deterministic future date relative to test execution."""
    day = datetime.now() + timedelta(days=3)
    start = day.replace(hour=10, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=2)
    return start, end


def create_reservation(resource_id, user_id, start, end):
    response = client.post(
        "/reservations",
        json={
            "resource_id": resource_id,
            "user_id": user_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def confirm(reservation_id):
    return client.post(f"/reservations/{reservation_id}/confirm")


def availability(resource_id, start, end):
    return client.post(
        "/availability",
        json={
            "resource_id": resource_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
    )


def approve(reservation_id, decision="approve", admin_id="Admin1"):
    return client.post(
        f"/reservations/{reservation_id}/approval",
        json={"admin_id": admin_id, "decision": decision},
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )


# ---------------------------------------------------------------------------
# H1: Interval validation and half-open interval boundaries
# ---------------------------------------------------------------------------


def test_hard_interval_start_equal_to_end_is_rejected(future_slot):
    start, _ = future_slot
    response = client.post(
        "/reservations",
        json={
            "resource_id": "Room-A",
            "user_id": "User-A",
            "start_time": start.isoformat(),
            "end_time": start.isoformat(),
        },
    )
    assert response.status_code == 400


def test_hard_interval_end_before_start_is_rejected(future_slot):
    start, _ = future_slot
    response = client.post(
        "/availability",
        json={
            "resource_id": "Room-A",
            "start_time": (start + timedelta(hours=2)).isoformat(),
            "end_time": start.isoformat(),
        },
    )
    assert response.status_code == 400


def test_hard_adjacent_confirmed_reservations_do_not_conflict(future_slot):
    start, end = future_slot
    first_id = create_reservation("Room-A", "User-A", start, end)
    assert confirm(first_id).status_code == 200

    second_start = end
    second_end = end + timedelta(hours=1)
    second_id = create_reservation("Room-A", "User-B", second_start, second_end)
    response = confirm(second_id)

    assert response.status_code == 200
    assert response.json()["state"] == "CONFIRMED"


def test_hard_partial_overlap_is_rejected(future_slot):
    start, end = future_slot
    first_id = create_reservation("Room-A", "User-A", start, end)
    assert confirm(first_id).status_code == 200

    second_id = create_reservation(
        "Room-A",
        "User-B",
        start + timedelta(minutes=90),
        end + timedelta(minutes=90),
    )
    response = confirm(second_id)

    assert response.status_code == 409


def test_hard_contained_interval_is_rejected(future_slot):
    start, end = future_slot
    first_id = create_reservation("Room-A", "User-A", start, end)
    assert confirm(first_id).status_code == 200

    second_id = create_reservation(
        "Room-A",
        "User-B",
        start + timedelta(minutes=30),
        end - timedelta(minutes=30),
    )
    assert confirm(second_id).status_code == 409


def test_hard_same_time_different_rooms_can_be_confirmed(future_slot):
    start, end = future_slot
    first_id = create_reservation("Room-A", "User-A", start, end)
    second_id = create_reservation("Room-B", "User-B", start, end)

    assert confirm(first_id).status_code == 200
    assert confirm(second_id).status_code == 200


# ---------------------------------------------------------------------------
# H2: Daily quota boundaries
# ---------------------------------------------------------------------------


def test_hard_exactly_four_hour_booking_is_allowed():
    day = datetime.now() + timedelta(days=4)
    start = day.replace(hour=8, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=4)

    response = client.post(
        "/reservations",
        json={
            "resource_id": "Room-A",
            "user_id": "User-A",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
    )
    assert response.status_code == 200


def test_hard_two_bookings_cannot_exceed_four_hour_daily_quota():
    day = datetime.now() + timedelta(days=4)
    start = day.replace(hour=8, minute=0, second=0, microsecond=0)

    first_id = create_reservation("Room-A", "User-A", start, start + timedelta(hours=2))
    assert first_id is not None

    response = client.post(
        "/reservations",
        json={
            "resource_id": "Room-B",
            "user_id": "User-A",
            "start_time": (start + timedelta(hours=3)).isoformat(),
            "end_time": (start + timedelta(hours=5, minutes=1)).isoformat(),
        },
    )
    assert response.status_code == 400
    assert "4-hour daily limit exceeded" in response.json()["detail"]


def test_hard_cancelled_reservation_does_not_count_toward_daily_quota():
    day = datetime.now() + timedelta(days=4)
    start = day.replace(hour=8, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=3)

    reservation_id = create_reservation("Room-A", "User-A", start, end)
    cancel_response = client.post(f"/reservations/{reservation_id}/cancel")
    assert cancel_response.status_code == 200

    new_id = create_reservation(
        "Room-B",
        "User-A",
        start + timedelta(hours=3),
        start + timedelta(hours=4, minutes=30),
    )
    assert new_id is not None


# ---------------------------------------------------------------------------
# H3: State transition rules and idempotency
# ---------------------------------------------------------------------------


def test_hard_confirming_already_confirmed_reservation_is_rejected(future_slot):
    start, end = future_slot
    reservation_id = create_reservation("Room-A", "User-A", start, end)

    first = confirm(reservation_id)
    second = confirm(reservation_id)

    assert first.status_code == 200
    assert second.status_code == 400


def test_hard_cannot_approve_standard_room_reservation(future_slot):
    start, end = future_slot
    reservation_id = create_reservation("Room-A", "User-A", start, end)
    assert confirm(reservation_id).json()["state"] == "CONFIRMED"

    response = approve(reservation_id)
    assert response.status_code == 400


def test_hard_cannot_reject_standard_room_reservation(future_slot):
    start, end = future_slot
    reservation_id = create_reservation("Room-A", "User-A", start, end)
    assert confirm(reservation_id).status_code == 200

    response = approve(reservation_id, decision="reject")
    assert response.status_code == 400


def test_hard_cannot_approve_same_vip_reservation_twice(future_slot):
    start, end = future_slot
    reservation_id = create_reservation("VIP_Room-A", "User-A", start, end)
    assert confirm(reservation_id).json()["state"] == "PENDING_APPROVAL"

    first = approve(reservation_id)
    second = approve(reservation_id)

    assert first.status_code == 200
    assert second.status_code == 400


def test_hard_cancelled_reservation_cannot_be_confirmed(future_slot):
    start, end = future_slot
    reservation_id = create_reservation("Room-A", "User-A", start, end)

    cancelled = client.post(f"/reservations/{reservation_id}/cancel")
    assert cancelled.status_code == 200

    response = confirm(reservation_id)
    assert response.status_code == 400


def test_hard_missing_reservation_returns_404():
    response = confirm(999999)
    assert response.status_code == 404


def test_hard_cancel_after_start_is_rejected(future_slot):
    start, end = future_slot
    reservation_id = create_reservation("Room-A", "User-A", start, end)

    # The endpoint uses the actual current time, so a future reservation
    # can still be cancelled. This test instead checks a past-start booking.
    past_start = datetime.now() - timedelta(hours=2)
    past_end = datetime.now() - timedelta(hours=1)
    past_id = create_reservation("Room-B", "User-B", past_start, past_end)

    response = client.post(f"/reservations/{past_id}/cancel")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# H4: VIP approval conflicts and expiry
# ---------------------------------------------------------------------------


def test_hard_pending_vip_reservation_does_not_block_another_pending_request(
    future_slot,
):
    start, end = future_slot
    first_id = create_reservation("VIP_Room-A", "User-A", start, end)
    second_id = create_reservation("VIP_Room-A", "User-B", start, end)

    assert confirm(first_id).json()["state"] == "PENDING_APPROVAL"
    assert confirm(second_id).json()["state"] == "PENDING_APPROVAL"

    assert approve(first_id).status_code == 200
    assert approve(second_id).status_code == 409


def test_hard_confirm_past_reservation_is_rejected():
    past_start = datetime.now() - timedelta(hours=2)
    past_end = datetime.now() - timedelta(hours=1)
    reservation_id = create_reservation("VIP_Room-A", "User-A", past_start, past_end)

    response = confirm(reservation_id)
    assert response.status_code == 400
    assert "Cannot confirm a reservation in the past" in response.json()["detail"]


def test_hard_rejecting_vip_reservation_makes_slot_available(future_slot):
    start, end = future_slot
    reservation_id = create_reservation("VIP_Room-A", "User-A", start, end)
    assert confirm(reservation_id).json()["state"] == "PENDING_APPROVAL"

    assert approve(reservation_id, decision="reject").json()["state"] == "CANCELLED"
    assert availability("VIP_Room-A", start, end).json()["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# H5: API request validation
# ---------------------------------------------------------------------------


def test_hard_unknown_approval_decision_is_rejected(future_slot):
    start, end = future_slot
    reservation_id = create_reservation("VIP_Room-A", "User-A", start, end)
    assert confirm(reservation_id).status_code == 200

    response = client.post(
        f"/reservations/{reservation_id}/approval",
        json={"admin_id": "Admin1", "decision": "maybe"},
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )

    assert response.status_code == 422


def test_hard_missing_required_create_field_is_rejected(future_slot):
    start, end = future_slot
    response = client.post(
        "/reservations",
        json={
            "resource_id": "Room-A",
            "user_id": "User-A",
            "start_time": start.isoformat(),
            # end_time intentionally omitted
        },
    )
    assert response.status_code == 422


def test_hard_availability_invalid_interval_is_rejected(future_slot):
    start, end = future_slot
    response = availability("Room-A", end, start)
    assert response.status_code == 400
