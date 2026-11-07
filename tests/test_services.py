from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import IncidentType, Route, RouteStop, Stop, Trip, TripStatus
from app.services import eta_service, incident_service


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = Session()

    # Create base entities: 1 route, 1 stop, 1 routestop, 1 trip
    route = Route(name="Campus Express")
    stop = Stop(name="Library Center")
    session.add_all([route, stop])
    session.flush()

    route_stop = RouteStop(
        route_id=route.id,
        stop_id=stop.id,
        sequence=1,
        offset_minutes=15,
    )
    session.add(route_stop)
    session.flush()

    departure = datetime(2026, 11, 7, 10, 0, 0, tzinfo=timezone.utc)
    trip = Trip(
        route_id=route.id,
        scheduled_departure=departure,
        status=TripStatus.SCHEDULED,
    )
    session.add(trip)
    session.commit()
    session.refresh(trip)
    session.refresh(route_stop)

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)


def test_no_incident_on_time(db):
    trip = db.query(Trip).first()
    route_stop = db.query(RouteStop).first()
    now = datetime(2026, 11, 7, 10, 5, 0, tzinfo=timezone.utc)

    status = eta_service.stop_status(trip, route_stop, now=now)

    expected_scheduled = datetime(2026, 11, 7, 10, 15, 0, tzinfo=timezone.utc)
    assert status["scheduled_time"] == expected_scheduled
    assert status["estimated_time"] == expected_scheduled
    assert status["delay_minutes"] == 0
    assert status["status"] == "ON_TIME"
    assert status["message"] is None
    assert status["last_updated"] is None
    assert status["is_stale"] is False


def test_delay_shifts_eta(db):
    trip = db.query(Trip).first()
    route_stop = db.query(RouteStop).first()
    incident_time = datetime(2026, 11, 7, 10, 2, 0, tzinfo=timezone.utc)

    inc = incident_service.report_incident(
        db=db,
        trip_id=trip.id,
        type=IncidentType.DELAY,
        delay_minutes=20,
        message="Stuck in highway traffic",
        created_by="dispatcher_dan",
        now=incident_time,
    )

    assert inc.is_active is True
    assert trip.status == TripStatus.DELAYED

    status = eta_service.stop_status(trip, route_stop, now=incident_time)

    expected_scheduled = datetime(2026, 11, 7, 10, 15, 0, tzinfo=timezone.utc)
    expected_estimated = datetime(2026, 11, 7, 10, 35, 0, tzinfo=timezone.utc)

    assert status["scheduled_time"] == expected_scheduled
    assert status["estimated_time"] == expected_estimated
    assert status["delay_minutes"] == 20
    assert status["status"] == "DELAYED"
    assert status["message"] == "Stuck in highway traffic"
    assert status["last_updated"] == incident_time
    assert status["is_stale"] is False


def test_supersede(db):
    trip = db.query(Trip).first()
    time_1 = datetime(2026, 11, 7, 10, 0, 0, tzinfo=timezone.utc)
    time_2 = datetime(2026, 11, 7, 10, 5, 0, tzinfo=timezone.utc)

    inc1 = incident_service.report_incident(
        db=db,
        trip_id=trip.id,
        type=IncidentType.DELAY,
        delay_minutes=15,
        message="Minor delay",
        created_by="dispatcher_1",
        now=time_1,
    )
    assert inc1.is_active is True
    assert trip.status == TripStatus.DELAYED

    inc2 = incident_service.report_incident(
        db=db,
        trip_id=trip.id,
        type=IncidentType.BREAKDOWN,
        delay_minutes=None,
        message="Engine overheated",
        created_by="dispatcher_2",
        now=time_2,
    )

    db.refresh(inc1)
    db.refresh(inc2)
    db.refresh(trip)

    # First incident superseded and deactivated
    assert inc1.is_active is False
    assert inc2.is_active is True
    assert trip.status == TripStatus.BROKEN_DOWN

    # History audit trail contains both, newest first
    hist = incident_service.history(db, trip.id)
    assert len(hist) == 2
    assert hist[0].id == inc2.id
    assert hist[1].id == inc1.id


def test_resolve(db):
    trip = db.query(Trip).first()
    route_stop = db.query(RouteStop).first()
    time_breakdown = datetime(2026, 11, 7, 10, 0, 0, tzinfo=timezone.utc)
    time_resolved = datetime(2026, 11, 7, 10, 15, 0, tzinfo=timezone.utc)

    inc_breakdown = incident_service.report_incident(
        db=db,
        trip_id=trip.id,
        type=IncidentType.BREAKDOWN,
        delay_minutes=None,
        message="Flat tire",
        created_by="dispatcher_1",
        now=time_breakdown,
    )
    assert inc_breakdown.is_active is True
    assert trip.status == TripStatus.BROKEN_DOWN

    inc_resolved = incident_service.report_incident(
        db=db,
        trip_id=trip.id,
        type=IncidentType.RESOLVED,
        delay_minutes=None,
        message="Tire replaced, resuming normal route",
        created_by="dispatcher_1",
        now=time_resolved,
    )

    db.refresh(inc_breakdown)
    db.refresh(trip)

    assert inc_breakdown.is_active is False
    assert inc_resolved.is_active is False
    assert trip.status == TripStatus.SCHEDULED

    # ETA status should now be back to ON_TIME
    status = eta_service.stop_status(trip, route_stop, now=time_resolved)
    assert status["status"] == "ON_TIME"
    assert status["delay_minutes"] == 0
    assert status["message"] is None
    assert status["last_updated"] is None
    assert status["is_stale"] is False
    assert status["estimated_time"] == status["scheduled_time"]


def test_stale_flag(db):
    trip = db.query(Trip).first()
    route_stop = db.query(RouteStop).first()
    created_time = datetime(2026, 11, 7, 10, 0, 0, tzinfo=timezone.utc)

    incident_service.report_incident(
        db=db,
        trip_id=trip.id,
        type=IncidentType.DELAY,
        delay_minutes=10,
        message="Traffic queue",
        created_by="dispatcher",
        now=created_time,
    )

    # 5 minutes later: not stale
    now_5m = created_time + timedelta(minutes=5)
    status_5m = eta_service.stop_status(trip, route_stop, now=now_5m)
    assert status_5m["is_stale"] is False

    # 10 minutes later: threshold boundary is not stale (> 10 min)
    now_10m = created_time + timedelta(minutes=10)
    status_10m = eta_service.stop_status(trip, route_stop, now=now_10m)
    assert status_10m["is_stale"] is False

    # 10 minutes and 1 second later: stale
    now_10m_1s = created_time + timedelta(minutes=10, seconds=1)
    status_10m_1s = eta_service.stop_status(trip, route_stop, now=now_10m_1s)
    assert status_10m_1s["is_stale"] is True


def test_cancellation_and_breakdown_have_no_eta(db):
    trip = db.query(Trip).first()
    route_stop = db.query(RouteStop).first()
    now = datetime(2026, 11, 7, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Cancellation
    incident_service.report_incident(
        db=db,
        trip_id=trip.id,
        type=IncidentType.CANCELLATION,
        delay_minutes=None,
        message="Route cancelled due to weather",
        created_by="dispatcher",
        now=now,
    )
    status_cancel = eta_service.stop_status(trip, route_stop, now=now)
    assert status_cancel["estimated_time"] is None
    assert status_cancel["status"] == "CANCELLED"
    assert status_cancel["message"] == "Route cancelled due to weather"
    assert status_cancel["scheduled_time"] is not None

    # 2. Breakdown
    incident_service.report_incident(
        db=db,
        trip_id=trip.id,
        type=IncidentType.BREAKDOWN,
        delay_minutes=None,
        message="Mechanical breakdown",
        created_by="dispatcher",
        now=now,
    )
    status_breakdown = eta_service.stop_status(trip, route_stop, now=now)
    assert status_breakdown["estimated_time"] is None
    assert status_breakdown["status"] == "BROKEN_DOWN"
    assert status_breakdown["message"] == "Mechanical breakdown"


def test_validation_errors(db):
    trip = db.query(Trip).first()

    # DELAY requires delay_minutes > 0
    with pytest.raises(ValueError, match="delay_minutes > 0"):
        incident_service.report_incident(
            db=db,
            trip_id=trip.id,
            type=IncidentType.DELAY,
            delay_minutes=0,
            message="No delay",
            created_by="dispatcher",
        )

    with pytest.raises(ValueError, match="delay_minutes > 0"):
        incident_service.report_incident(
            db=db,
            trip_id=trip.id,
            type=IncidentType.DELAY,
            delay_minutes=-5,
            message="Negative delay",
            created_by="dispatcher",
        )

    with pytest.raises(ValueError, match="delay_minutes > 0"):
        incident_service.report_incident(
            db=db,
            trip_id=trip.id,
            type=IncidentType.DELAY,
            delay_minutes=None,
            message="Missing delay",
            created_by="dispatcher",
        )

    # Trip must exist
    with pytest.raises(ValueError, match="not found"):
        incident_service.report_incident(
            db=db,
            trip_id=99999,
            type=IncidentType.BREAKDOWN,
            delay_minutes=None,
            message="Unknown trip",
            created_by="dispatcher",
        )

    # Invalid incident type string
    with pytest.raises(ValueError, match="Invalid incident type"):
        incident_service.report_incident(
            db=db,
            trip_id=trip.id,
            type="INVALID_TYPE",
            delay_minutes=None,
            message="Invalid",
            created_by="dispatcher",
        )
