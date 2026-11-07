from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Route, RouteStop, Stop, Trip, TripStatus
from seed import seed_data


@pytest.fixture
def e2e_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()

    # Seed data with current time window
    base_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    seed_data(db, base_time=base_time)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, db

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_static_pages_served(e2e_client):
    client, _ = e2e_client

    # 1. Rider page at /
    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "Where's My Bus?" in r_home.text
    assert "/static/styles.css" in r_home.text

    # 2. Staff page at /staff
    r_staff = client.get("/staff")
    assert r_staff.status_code == 200
    assert "Staff Portal" in r_staff.text
    assert "Quick Incident Logger" in r_staff.text


def test_complete_disruption_and_rider_notification_flow(e2e_client):
    client, db = e2e_client
    headers = {"X-Staff-Key": "dev-key"}

    # 1. Look up Stop 1 (Main Quad) and its upcoming trip
    stops_res = client.get("/api/stops")
    assert stops_res.status_code == 200
    stop1 = next(s for s in stops_res.json() if s["name"] == "Main Quad")
    stop1_id = stop1["id"]

    # 2. Rider (user_alice) checks arrivals -> initially ON_TIME
    arrivals_before = client.get(f"/api/stops/{stop1_id}/arrivals").json()
    assert len(arrivals_before) > 0
    target_trip_id = arrivals_before[0]["trip_id"]
    target_route_id = arrivals_before[0]["route_id"]
    assert arrivals_before[0]["status"] == "ON_TIME"

    # 3. Rider subscribes to this route & stop
    sub_res = client.post(
        "/api/subscriptions",
        json={"user_ref": "rider_clara", "route_id": target_route_id, "stop_id": stop1_id},
    )
    assert sub_res.status_code == 201

    # 4. Staff reports a 20-minute delay on the trip
    inc_res = client.post(
        "/api/staff/incidents",
        headers=headers,
        json={
            "trip_id": target_trip_id,
            "type": "DELAY",
            "delay_minutes": 20,
            "message": "Heavy campus traffic near construction zone",
            "created_by": "dispatcher_sarah",
        },
    )
    assert inc_res.status_code == 201
    assert inc_res.json()["is_active"] is True

    # 5. Rider checks arrival board again -> ETA is shifted, status DELAYED
    arrivals_after = client.get(f"/api/stops/{stop1_id}/arrivals").json()
    delayed_arrival = next(a for a in arrivals_after if a["trip_id"] == target_trip_id)
    assert delayed_arrival["status"] == "DELAYED"
    assert delayed_arrival["delay_minutes"] == 20
    assert "Heavy campus traffic" in delayed_arrival["message"]

    # 6. Rider checks personal inbox -> notification arrived with updated ETA!
    inbox_res = client.get("/api/inbox/rider_clara")
    assert inbox_res.status_code == 200
    notifs = inbox_res.json()
    assert len(notifs) == 1
    assert "delayed 20 min" in notifs[0]["message"]
    assert "Heavy campus traffic" in notifs[0]["message"]

    # 7. Staff summary reflects the active incident and sent notification
    summary_res = client.get("/api/staff/summary", headers=headers)
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["active_incidents"] >= 1
    assert summary["total_notifications_sent"] >= 1

    # 8. Staff resolves the incident
    resolve_res = client.post(
        f"/api/staff/incidents/{target_trip_id}/resolve",
        headers=headers,
        json={"message": "Road cleared, normal route resumed.", "created_by": "dispatcher_sarah"},
    )
    assert resolve_res.status_code == 200

    # 9. Rider arrival board is back to ON_TIME
    arrivals_resolved = client.get(f"/api/stops/{stop1_id}/arrivals").json()
    resolved_arrival = next(a for a in arrivals_resolved if a["trip_id"] == target_trip_id)
    assert resolved_arrival["status"] == "ON_TIME"
    assert resolved_arrival["delay_minutes"] == 0

    # 10. Rider inbox contains service restored alert
    inbox_res2 = client.get("/api/inbox/rider_clara")
    notifs2 = inbox_res2.json()
    assert len(notifs2) == len(notifs) + 1
    assert "back on schedule" in notifs2[0]["message"]
