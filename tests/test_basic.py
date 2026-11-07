from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db import Base
from app.main import app
from app.models import Route, Stop, RouteStop, Trip, Subscription, Incident, Notification
from seed import seed_data


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_seed_idempotency(test_db):
    base_time = datetime(2026, 11, 7, 8, 0, 0, tzinfo=timezone.utc)
    
    # First seed
    seed_data(test_db, base_time=base_time)
    routes_count = test_db.query(Route).count()
    stops_count = test_db.query(Stop).count()
    route_stops_count = test_db.query(RouteStop).count()
    trips_count = test_db.query(Trip).count()
    subs_count = test_db.query(Subscription).count()

    assert routes_count == 2
    assert stops_count == 6
    assert route_stops_count == 8
    assert trips_count == 48  # 2 routes * 24 hours
    assert subs_count == 3

    # Second seed (idempotency check)
    seed_data(test_db, base_time=base_time)
    assert test_db.query(Route).count() == routes_count
    assert test_db.query(Stop).count() == stops_count
    assert test_db.query(RouteStop).count() == route_stops_count
    assert test_db.query(Trip).count() == trips_count
    assert test_db.query(Subscription).count() == subs_count


def test_app_health_and_root():
    client = TestClient(app)
    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json() == {"status": "ok"}

    root_resp = client.get("/")
    assert root_resp.status_code == 200
    assert "Campus Transport Experience" in root_resp.text
