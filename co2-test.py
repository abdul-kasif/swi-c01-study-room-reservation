import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
from src.main import app, Base, engine


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


client = TestClient(app)

tomorrow = datetime.now() + timedelta(days=1)
start_str = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
end_str = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0).isoformat()
long_end_str = tomorrow.replace(hour=15, minute=0, second=0, microsecond=0).isoformat()

# --- Baseline v0.1 Tests ---


def test_op01_create_success():
    response = client.post(
        "/reservations",
        json={
            "resource_id": "Room1",
            "user_id": "UserA",
            "start_time": start_str,
            "end_time": end_str,
        },
    )
    assert response.status_code == 200
    assert response.json()["state"] == "DRAFT"


def test_op01_create_negative_limit_exceeded():
    response = client.post(
        "/reservations",
        json={
            "resource_id": "Room1",
            "user_id": "UserB",
            "start_time": start_str,
            "end_time": long_end_str,
        },
    )
    assert response.status_code == 400
    assert "4-hour daily limit exceeded" in response.json()["detail"]


def test_op02_availability_success():
    response = client.post(
        "/availability",
        json={"resource_id": "Room2", "start_time": start_str, "end_time": end_str},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "AVAILABLE"


def test_op03_confirm_standard_room_and_op02_negative():
    create_res = client.post(
        "/reservations",
        json={
            "resource_id": "Room2",
            "user_id": "UserC",
            "start_time": start_str,
            "end_time": end_str,
        },
    )
    res_id = create_res.json()["id"]

    confirm_res = client.post(f"/reservations/{res_id}/confirm")
    assert confirm_res.status_code == 200
    assert confirm_res.json()["state"] == "CONFIRMED"

    avail_res = client.post(
        "/availability",
        json={"resource_id": "Room2", "start_time": start_str, "end_time": end_str},
    )
    assert avail_res.json()["status"] == "UNAVAILABLE"


def test_op03_confirm_negative_overlap():
    r1 = client.post(
        "/reservations",
        json={
            "resource_id": "Room2",
            "user_id": "UserC",
            "start_time": start_str,
            "end_time": end_str,
        },
    ).json()["id"]
    client.post(f"/reservations/{r1}/confirm")

    r2 = client.post(
        "/reservations",
        json={
            "resource_id": "Room2",
            "user_id": "UserD",
            "start_time": start_str,
            "end_time": end_str,
        },
    ).json()["id"]

    confirm_res = client.post(f"/reservations/{r2}/confirm")
    assert confirm_res.status_code == 409
    assert "Conflict" in confirm_res.json()["detail"]


def test_op04_cancel_success_and_idempotent():
    res_id = client.post(
        "/reservations",
        json={
            "resource_id": "Room3",
            "user_id": "UserE",
            "start_time": start_str,
            "end_time": end_str,
        },
    ).json()["id"]

    cancel_res = client.post(f"/reservations/{res_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["state"] == "CANCELLED"

    # Idempotent repeat cancel
    repeat_res = client.post(f"/reservations/{res_id}/cancel")
    assert repeat_res.status_code == 200
    assert repeat_res.json()["state"] == "CANCELLED"


def test_op04_cancel_negative_past_start_time():
    past_start = (datetime.now() - timedelta(hours=2)).isoformat()
    past_end = (datetime.now() - timedelta(hours=1)).isoformat()

    res_id = client.post(
        "/reservations",
        json={
            "resource_id": "Room4",
            "user_id": "UserF",
            "start_time": past_start,
            "end_time": past_end,
        },
    ).json()["id"]

    cancel_res = client.post(f"/reservations/{res_id}/cancel")
    assert cancel_res.status_code == 400
    assert "Cannot cancel after the start time" in cancel_res.json()["detail"]


# --- Baseline v0.2 Change (Approval Workflow) Tests ---


def test_op05_restricted_room_requires_approval_and_succeeds():
    res_id = client.post(
        "/reservations",
        json={
            "resource_id": "VIP_Room1",
            "user_id": "UserG",
            "start_time": start_str,
            "end_time": end_str,
        },
    ).json()["id"]

    # Confirm transitions to PENDING_APPROVAL instead of CONFIRMED
    confirm_res = client.post(f"/reservations/{res_id}/confirm")
    assert confirm_res.status_code == 200
    assert confirm_res.json()["state"] == "PENDING_APPROVAL"

    # Room is still AVAILABLE while only PENDING_APPROVAL
    avail_res = client.post(
        "/availability",
        json={"resource_id": "VIP_Room1", "start_time": start_str, "end_time": end_str},
    )
    assert avail_res.json()["status"] == "AVAILABLE"

    # Admin approves the request
    approve_res = client.post(
        f"/reservations/{res_id}/approval",
        json={"admin_id": "Admin1", "decision": "approve"},
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["state"] == "CONFIRMED"

    # Now room is UNAVAILABLE
    avail_after = client.post(
        "/availability",
        json={"resource_id": "VIP_Room1", "start_time": start_str, "end_time": end_str},
    )
    assert avail_after.json()["status"] == "UNAVAILABLE"


def test_op05_admin_rejection_sets_cancelled():
    res_id = client.post(
        "/reservations",
        json={
            "resource_id": "VIP_Room2",
            "user_id": "UserH",
            "start_time": start_str,
            "end_time": end_str,
        },
    ).json()["id"]
    client.post(f"/reservations/{res_id}/confirm")

    reject_res = client.post(
        f"/reservations/{res_id}/approval",
        json={"admin_id": "Admin1", "decision": "reject"},
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["state"] == "CANCELLED"


def test_op05_approval_conflict_when_two_pending_compete():
    r1 = client.post(
        "/reservations",
        json={
            "resource_id": "VIP_Room3",
            "user_id": "UserI",
            "start_time": start_str,
            "end_time": end_str,
        },
    ).json()["id"]
    r2 = client.post(
        "/reservations",
        json={
            "resource_id": "VIP_Room3",
            "user_id": "UserJ",
            "start_time": start_str,
            "end_time": end_str,
        },
    ).json()["id"]

    # Both enter PENDING_APPROVAL
    client.post(f"/reservations/{r1}/confirm")
    client.post(f"/reservations/{r2}/confirm")

    # Admin approves first reservation -> CONFIRMED
    res1 = client.post(
        f"/reservations/{r1}/approval",
        json={"admin_id": "Admin1", "decision": "approve"},
    )
    assert res1.status_code == 200

    # Admin tries to approve second overlapping reservation -> 409 Conflict
    res2 = client.post(
        f"/reservations/{r2}/approval",
        json={"admin_id": "Admin1", "decision": "approve"},
    )
    assert res2.status_code == 409
