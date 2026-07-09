import time

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_export_does_not_leak_other_org_bookings_when_room_id_is_supplied():
    org1 = f"acme-{time.time_ns()}"
    org2 = f"beta-{time.time_ns()}"

    reg1 = client.post(
        "/auth/register",
        json={"org_name": org1, "username": "alice", "password": "pw12345"},
    )
    assert reg1.status_code == 201

    login1 = client.post(
        "/auth/login",
        json={"org_name": org1, "username": "alice", "password": "pw12345"},
    )
    headers1 = {"Authorization": f"Bearer {login1.json()['access_token']}"}

    room1 = client.post(
        "/rooms",
        json={"name": "Hub", "capacity": 6, "hourly_rate_cents": 1500},
        headers=headers1,
    )
    assert room1.status_code == 201
    room1_id = room1.json()["id"]

    future = 48
    booking = client.post(
        "/bookings",
        json={
            "room_id": room1_id,
            "start_time": f"2099-01-01T00:00:00+00:00",
            "end_time": f"2099-01-01T01:00:00+00:00",
        },
        headers=headers1,
    )
    assert booking.status_code == 201

    reg2 = client.post(
        "/auth/register",
        json={"org_name": org2, "username": "bob", "password": "pw12345"},
    )
    assert reg2.status_code == 201

    login2 = client.post(
        "/auth/login",
        json={"org_name": org2, "username": "bob", "password": "pw12345"},
    )
    headers2 = {"Authorization": f"Bearer {login2.json()['access_token']}"}

    export = client.get(
        "/admin/export",
        params={"room_id": room1_id, "include_all": True},
        headers=headers2,
    )
    assert export.status_code == 200
    assert booking.json()["reference_code"] not in export.text
