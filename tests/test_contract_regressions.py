"""Focused contract regressions for the seeded bug-fix challenge."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import csv
import io
import uuid

import jwt
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app, raise_server_exceptions=False)


def _org(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _future(hours: int) -> str:
    return (
        datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        + timedelta(hours=hours)
    ).isoformat()


def _register(org: str, username: str = "alice"):
    return client.post(
        "/auth/register",
        json={"org_name": org, "username": username, "password": "pw12345"},
    )


def _login(org: str, username: str = "alice") -> dict:
    response = client.post(
        "/auth/login",
        json={"org_name": org, "username": username, "password": "pw12345"},
    )
    assert response.status_code == 200
    return response.json()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _room(token: str, rate: int = 1000) -> int:
    response = client.post(
        "/rooms",
        json={"name": f"Room {uuid.uuid4().hex[:6]}", "capacity": 4, "hourly_rate_cents": rate},
        headers=_headers(token),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _book(token: str, room_id: int, start: str, end: str):
    return client.post(
        "/bookings",
        json={"room_id": room_id, "start_time": start, "end_time": end},
        headers=_headers(token),
    )


def test_auth_expiry_logout_refresh_and_duplicate_registration():
    org = _org("auth")
    assert _register(org).status_code == 201
    duplicate = _register(org)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "USERNAME_TAKEN"

    tokens = _login(org)
    payload = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    assert payload["exp"] - payload["iat"] == 900

    refresh_once = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh_once.status_code == 200
    refresh_twice = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh_twice.status_code == 401

    logout = client.post("/auth/logout", headers=_headers(tokens["access_token"]))
    assert logout.status_code == 200
    assert client.get("/rooms", headers=_headers(tokens["access_token"])).status_code == 401


def test_booking_windows_utc_overlap_and_pagination():
    org = _org("booking")
    _register(org)
    token = _login(org)["access_token"]
    room_id = _room(token)

    past = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=30)
    past_response = _book(token, room_id, past.isoformat(), (past + timedelta(hours=1)).isoformat())
    assert past_response.status_code == 400

    zero = _book(token, room_id, _future(40), _future(40))
    assert zero.status_code == 400

    negative = _book(token, room_id, _future(42), _future(41))
    assert negative.status_code == 400

    start_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=50)
    start_offset = start_utc.astimezone(timezone(timedelta(hours=6))).isoformat()
    end_offset = (start_utc + timedelta(hours=1)).astimezone(timezone(timedelta(hours=6))).isoformat()
    offset_booking = _book(token, room_id, start_offset, end_offset)
    assert offset_booking.status_code == 201
    assert offset_booking.json()["start_time"] == start_utc.isoformat()

    first = _book(token, room_id, _future(60), _future(61))
    second = _book(token, room_id, _future(61), _future(62))
    assert first.status_code == 201
    assert second.status_code == 201

    list_response = client.get("/bookings?page=1&limit=2", headers=_headers(token))
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) == 2
    assert items == sorted(items, key=lambda item: (item["start_time"], item["id"]))


def test_booking_detail_visibility_and_refunds():
    org = _org("refund")
    _register(org, "admin")
    admin_token = _login(org, "admin")["access_token"]
    room_id = _room(admin_token, rate=1001)
    _register(org, "member1")
    _register(org, "member2")
    member1_token = _login(org, "member1")["access_token"]
    member2_token = _login(org, "member2")["access_token"]

    booking = _book(member1_token, room_id, _future(30), _future(31)).json()
    detail = client.get(f"/bookings/{booking['id']}", headers=_headers(member1_token))
    assert detail.status_code == 200
    assert detail.json()["start_time"] == booking["start_time"]

    other_member = client.get(f"/bookings/{booking['id']}", headers=_headers(member2_token))
    assert other_member.status_code == 404

    cancel = client.post(f"/bookings/{booking['id']}/cancel", headers=_headers(member1_token))
    assert cancel.status_code == 200
    assert cancel.json()["refund_percent"] == 50
    assert cancel.json()["refund_amount_cents"] == 501

    cancelled_detail = client.get(f"/bookings/{booking['id']}", headers=_headers(member1_token)).json()
    assert len(cancelled_detail["refunds"]) == 1
    assert cancelled_detail["refunds"][0]["amount_cents"] == cancel.json()["refund_amount_cents"]


def test_reports_availability_stats_and_export_are_live_and_scoped():
    org_a = _org("orga")
    org_b = _org("orgb")
    _register(org_a, "admin")
    token_a = _login(org_a, "admin")["access_token"]
    room_a = _room(token_a)
    day = (datetime.now(timezone.utc) + timedelta(days=8)).date().isoformat()

    before = client.get(f"/admin/usage-report?from={day}&to={day}", headers=_headers(token_a)).json()
    assert before["rooms"][0]["confirmed_bookings"] == 0

    booking = _book(token_a, room_a, f"{day}T10:00:00+00:00", f"{day}T11:00:00+00:00").json()
    after = client.get(f"/admin/usage-report?from={day}&to={day}", headers=_headers(token_a)).json()
    assert after["rooms"][0]["confirmed_bookings"] == 1
    assert after["rooms"][0]["revenue_cents"] == 1000

    stats = client.get(f"/rooms/{room_a}/stats", headers=_headers(token_a)).json()
    assert stats["total_confirmed_bookings"] == 1
    assert stats["total_revenue_cents"] == 1000

    availability = client.get(f"/rooms/{room_a}/availability?date={day}", headers=_headers(token_a)).json()
    assert len(availability["busy"]) == 1
    client.post(f"/bookings/{booking['id']}/cancel", headers=_headers(token_a))
    availability_after_cancel = client.get(
        f"/rooms/{room_a}/availability?date={day}",
        headers=_headers(token_a),
    ).json()
    assert availability_after_cancel["busy"] == []

    _register(org_b, "admin")
    token_b = _login(org_b, "admin")["access_token"]
    leaked_export = client.get(
        f"/admin/export?include_all=true&room_id={room_a}",
        headers=_headers(token_b),
    )
    assert leaked_export.status_code == 404


def test_concurrent_double_booking_quota_reference_and_cancel():
    org = _org("race")
    _register(org, "admin")
    admin_token = _login(org, "admin")["access_token"]
    rooms = [_room(admin_token) for _ in range(5)]

    def same_slot():
        return _book(admin_token, rooms[0], _future(100), _future(101)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = [f.result() for f in as_completed([pool.submit(same_slot) for _ in range(2)])]
    assert sorted(statuses) == [201, 409]

    _register(org, "member")
    member_token = _login(org, "member")["access_token"]

    def quota_booking(index: int):
        return _book(member_token, rooms[index + 1], _future(4 + index), _future(5 + index)).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        quota_statuses = [
            f.result() for f in as_completed([pool.submit(quota_booking, index) for index in range(4)])
        ]
    assert quota_statuses.count(201) == 3
    assert quota_statuses.count(409) == 1

    ref_rooms = [_room(admin_token) for _ in range(4)]

    def reference_booking(index: int):
        response = _book(admin_token, ref_rooms[index], _future(130 + index), _future(131 + index))
        return response.json()["reference_code"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = [
            f.result() for f in as_completed([pool.submit(reference_booking, index) for index in range(4)])
        ]
    assert len(codes) == len(set(codes))

    cancel_booking = _book(admin_token, rooms[0], _future(150), _future(151)).json()

    def cancel_once():
        return client.post(f"/bookings/{cancel_booking['id']}/cancel", headers=_headers(admin_token)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancel_statuses = [f.result() for f in as_completed([pool.submit(cancel_once) for _ in range(2)])]
    assert sorted(cancel_statuses) == [200, 409]

    detail = client.get(f"/bookings/{cancel_booking['id']}", headers=_headers(admin_token)).json()
    assert len(detail["refunds"]) == 1
