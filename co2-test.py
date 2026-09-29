import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
from src.main import app, Base, engine

# Recreate database for a clean test environment
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

client = TestClient(app)

# Future dates to ensure cancellation rules pass
tomorrow = datetime.now() + timedelta(days=1)
start_str = tomorrow.replace(hour=10, minute=0, second=0).isoformat()
end_str = tomorrow.replace(hour=12, minute=0, second=0).isoformat()
long_end_str = tomorrow.replace(hour=15, minute=0, second=0).isoformat()


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
    # Attempting to book 5 hours (exceeds 4-hour limit)
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


def test_op03_confirm_success_and_op02_negative():
    # Create and confirm a draft
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

    # OP-02 Negative: Check availability for the now-confirmed slot
    avail_res = client.post(
        "/availability",
        json={"resource_id": "Room2", "start_time": start_str, "end_time": end_str},
    )
    assert avail_res.json()["status"] == "UNAVAILABLE"


def test_op03_confirm_negative_overlap():
    # Create another draft for the same room/time
    create_res = client.post(
        "/reservations",
        json={
            "resource_id": "Room2",
            "user_id": "UserD",
            "start_time": start_str,
            "end_time": end_str,
        },
    )
    res_id = create_res.json()["id"]

    # Attempt to confirm, should fail because UserC already confirmed it
    confirm_res = client.post(f"/reservations/{res_id}/confirm")
    assert confirm_res.status_code == 409
    assert "Conflict" in confirm_res.json()["detail"]


def test_op04_cancel_success():
    create_res = client.post(
        "/reservations",
        json={
            "resource_id": "Room3",
            "user_id": "UserE",
            "start_time": start_str,
            "end_time": end_str,
        },
    )
    res_id = create_res.json()["id"]

    cancel_res = client.post(f"/reservations/{res_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["state"] == "CANCELLED"


def test_op04_cancel_negative_past_start_time():
    # Create reservation in the past
    past_start = (datetime.now() - timedelta(hours=2)).isoformat()
    past_end = (datetime.now() - timedelta(hours=1)).isoformat()

    create_res = client.post(
        "/reservations",
        json={
            "resource_id": "Room4",
            "user_id": "UserF",
            "start_time": past_start,
            "end_time": past_end,
        },
    )
    res_id = create_res.json()["id"]

    cancel_res = client.post(f"/reservations/{res_id}/cancel")
    assert cancel_res.status_code == 400
    assert "Cannot cancel after the start time" in cancel_res.json()["detail"]
