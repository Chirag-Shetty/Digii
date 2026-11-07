from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Route, RouteStop, Stop, Trip, TripStatus


@pytest.fixture
def client_with_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()

    # Seed test dataset: 1 Route, 2 Stops, 1 Trip
    route = Route(name="Route 1 Campus")
    stop1 = Stop(name="Quad Gate")
    stop2 = Stop(name="Science Hall")
    db.add_all([route, stop1, stop2])
    db.flush()

    rs1 = RouteStop(route_id=route.id, stop_id=stop1.id, sequence=1, offset_minutes=0)
    rs2 = RouteStop(route_id=route.id, stop_id=stop2.id, sequence=2, offset_minutes=15)
    db.add_all([rs1, rs2])
    db.flush()

    departure = datetime.now(timezone.utc) + timedelta(minutes=30)
    trip = Trip(route_id=route.id, scheduled_departure=departure, status=TripStatus.SCHEDULED)
    db.add(trip)
    db.commit()

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, db, {"route": route, "stop1": stop1, "stop2": stop2, "trip": trip}

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_staff_auth_missing_and_invalid_key(client_with_db):
    client, _, data = client_with_db

    # 1. Missing header -> 401
    resp_missing = client.get("/api/staff/trips")
    assert resp_missing.status_code == 401
    assert "Unauthorized" in resp_missing.json()["detail"]

    # 2. Invalid header -> 401
    resp_invalid = client.get("/api/staff/trips", headers={"X-Staff-Key": "wrong-secret"})
    assert resp_invalid.status_code == 401


def test_rider_api_happy_path(client_with_db):
    client, _, data = client_with_db
    stop1_id = data["stop1"].id
    route_id = data["route"].id

    # 1. GET /api/routes
    r_routes = client.get("/api/routes")
    assert r_routes.status_code == 200
    assert len(r_routes.json()) >= 1
    assert r_routes.json()[0]["name"] == "Route 1 Campus"

    # 2. GET /api/stops
    r_stops = client.get("/api/stops")
    assert r_stops.status_code == 200
    assert len(r_stops.json()) >= 2

    # 3. GET /api/stops/{stop_id}/arrivals
    r_arrivals = client.get(f"/api/stops/{stop1_id}/arrivals")
    assert r_arrivals.status_code == 200
    arrivals = r_arrivals.json()
    assert len(arrivals) >= 1
    assert arrivals[0]["status"] == "ON_TIME"
    assert arrivals[0]["stop_name"] == "Quad Gate"

    # 4. POST /api/subscriptions
    r_sub = client.post(
        "/api/subscriptions",
        json={"user_ref": "student_dan", "route_id": route_id, "stop_id": stop1_id},
    )
    assert r_sub.status_code == 201
    sub_data = r_sub.json()
    assert sub_data["user_ref"] == "student_dan"
    sub_id = sub_data["id"]

    # 5. GET /api/inbox/{user_ref} (initially empty)
    r_inbox = client.get("/api/inbox/student_dan")
    assert r_inbox.status_code == 200
    assert r_inbox.json() == []

    # 6. DELETE /api/subscriptions/{id}
    r_del = client.delete(f"/api/subscriptions/{sub_id}")
    assert r_del.status_code == 204

    # Confirm deleted -> 404
    r_del2 = client.delete(f"/api/subscriptions/{sub_id}")
    assert r_del2.status_code == 404


def test_staff_api_happy_path_and_lifecycle(client_with_db):
    client, _, data = client_with_db
    trip_id = data["trip"].id
    route_id = data["route"].id
    stop1_id = data["stop1"].id
    headers = {"X-Staff-Key": "dev-key"}

    # Subscribe student_anna so she gets notified
    client.post(
        "/api/subscriptions",
        json={"user_ref": "student_anna", "route_id": route_id, "stop_id": stop1_id},
    )

    # 1. GET /api/staff/trips
    r_trips = client.get("/api/staff/trips", headers=headers)
    assert r_trips.status_code == 200
    trips = r_trips.json()
    assert len(trips) == 1
    assert trips[0]["status"] == "SCHEDULED"

    # 2. POST /api/staff/incidents (Report Delay)
    r_inc = client.post(
        "/api/staff/incidents",
        headers=headers,
        json={
            "trip_id": trip_id,
            "type": "DELAY",
            "delay_minutes": 25,
            "message": "Traffic bottleneck at stadium",
            "created_by": "dispatcher_joe",
        },
    )
    assert r_inc.status_code == 201
    inc_data = r_inc.json()
    assert inc_data["delay_minutes"] == 25
    assert inc_data["is_active"] is True

    # Check student_anna inbox received the alert
    r_inbox = client.get("/api/inbox/student_anna")
    assert r_inbox.status_code == 200
    notifs = r_inbox.json()
    assert len(notifs) == 1
    assert "delayed 25 min" in notifs[0]["message"]

    # 3. GET /api/staff/summary
    r_summary = client.get("/api/staff/summary", headers=headers)
    assert r_summary.status_code == 200
    summary = r_summary.json()
    assert summary["active_incidents"] == 1
    assert summary["total_notifications_sent"] >= 1

    # 4. GET /api/staff/trips/{trip_id}/history
    r_hist = client.get(f"/api/staff/trips/{trip_id}/history", headers=headers)
    assert r_hist.status_code == 200
    assert len(r_hist.json()) == 1

    # 5. POST /api/staff/incidents/{trip_id}/resolve
    r_res = client.post(
        f"/api/staff/incidents/{trip_id}/resolve",
        headers=headers,
        json={"message": "Road cleared, on route", "created_by": "dispatcher_joe"},
    )
    assert r_res.status_code == 200
    assert r_res.json()["type"] == "RESOLVED"

    # Summary: active incidents should now be 0
    r_summary2 = client.get("/api/staff/summary", headers=headers)
    assert r_summary2.json()["active_incidents"] == 0


def test_api_validation_and_not_found_errors(client_with_db):
    client, _, data = client_with_db
    trip_id = data["trip"].id
    headers = {"X-Staff-Key": "dev-key"}

    # 1. DELAY with delay_minutes <= 0 -> 422
    r_bad_delay = client.post(
        "/api/staff/incidents",
        headers=headers,
        json={
            "trip_id": trip_id,
            "type": "DELAY",
            "delay_minutes": 0,
            "message": "Invalid delay",
            "created_by": "staff",
        },
    )
    assert r_bad_delay.status_code == 422

    # 2. Incident for non-existent trip -> 404
    r_bad_trip = client.post(
        "/api/staff/incidents",
        headers=headers,
        json={
            "trip_id": 99999,
            "type": "BREAKDOWN",
            "delay_minutes": None,
            "message": "Bad trip",
            "created_by": "staff",
        },
    )
    assert r_bad_trip.status_code == 404

    # 3. Non-existent stop arrivals -> 404
    r_bad_stop = client.get("/api/stops/99999/arrivals")
    assert r_bad_stop.status_code == 404

    # 4. History for non-existent trip -> 404
    r_bad_hist = client.get("/api/staff/trips/99999/history", headers=headers)
    assert r_bad_hist.status_code == 404

    # 5. Subscription with non-existent route -> 404
    r_bad_sub = client.post(
        "/api/subscriptions",
        json={"user_ref": "dan", "route_id": 99999, "stop_id": data["stop1"].id},
    )
    assert r_bad_sub.status_code == 404
