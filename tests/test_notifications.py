from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import IncidentType, Notification, Route, RouteStop, Stop, Subscription, Trip, TripStatus
from app.services import incident_service, notification_service


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = Session()

    # Route 1: Route 2 Red, Stop: Library (offset 12 min)
    r1 = Route(name="Route 2")
    r2 = Route(name="Route 5")
    s1 = Stop(name="Library")
    s2 = Stop(name="Student Center")
    s3 = Stop(name="Stadium")
    session.add_all([r1, r2, s1, s2, s3])
    session.flush()

    # Route 1 stops
    rs1 = RouteStop(route_id=r1.id, stop_id=s1.id, sequence=1, offset_minutes=12)
    rs2 = RouteStop(route_id=r1.id, stop_id=s2.id, sequence=2, offset_minutes=25)

    # Route 2 stops
    rs3 = RouteStop(route_id=r2.id, stop_id=s3.id, sequence=1, offset_minutes=10)

    session.add_all([rs1, rs2, rs3])
    session.flush()

    # Trips: Route 1 departs at 09:30 UTC
    departure = datetime(2026, 11, 7, 9, 30, 0, tzinfo=timezone.utc)
    t1 = Trip(route_id=r1.id, scheduled_departure=departure, status=TripStatus.SCHEDULED)
    t2 = Trip(route_id=r2.id, scheduled_departure=departure, status=TripStatus.SCHEDULED)
    session.add_all([t1, t2])
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)


def test_delay_notification_message_and_delivery(db, capsys):
    r1 = db.query(Route).filter_by(name="Route 2").first()
    r2 = db.query(Route).filter_by(name="Route 5").first()
    s1 = db.query(Stop).filter_by(name="Library").first()
    s3 = db.query(Stop).filter_by(name="Stadium").first()
    t1 = db.query(Trip).filter_by(route_id=r1.id).first()

    # Alice is subscribed to Route 2 at Library
    sub_alice = Subscription(user_ref="user_alice", route_id=r1.id, stop_id=s1.id)
    # Charlie is subscribed to Route 5 at Stadium
    sub_charlie = Subscription(user_ref="user_charlie", route_id=r2.id, stop_id=s3.id)
    db.add_all([sub_alice, sub_charlie])
    db.commit()

    now = datetime(2026, 11, 7, 9, 32, 0, tzinfo=timezone.utc)
    incident_service.report_incident(
        db=db,
        trip_id=t1.id,
        type=IncidentType.DELAY,
        delay_minutes=12,
        message="Heavy campus traffic",
        created_by="staff_jane",
        now=now,
    )

    # 1. Right subscribers are notified, others are not
    alice_notifs = notification_service.get_user_notifications(db, "user_alice")
    charlie_notifs = notification_service.get_user_notifications(db, "user_charlie")

    assert len(alice_notifs) == 1
    assert len(charlie_notifs) == 0

    # 2. Check message content
    msg = alice_notifs[0].message
    assert "Route 2 at Library: delayed 12 min" in msg
    assert "new ETA 9:54" in msg
    assert "Reason: Heavy campus traffic" in msg

    # 3. Check printed to console
    captured = capsys.readouterr()
    assert "[NOTIFICATION] To user_alice: Route 2 at Library" in captured.out


def test_cancellation_notification_message(db):
    r1 = db.query(Route).filter_by(name="Route 2").first()
    s1 = db.query(Stop).filter_by(name="Library").first()
    t1 = db.query(Trip).filter_by(route_id=r1.id).first()

    sub = Subscription(user_ref="user_bob", route_id=r1.id, stop_id=s1.id)
    db.add(sub)
    db.commit()

    incident_service.report_incident(
        db=db,
        trip_id=t1.id,
        type=IncidentType.CANCELLATION,
        delay_minutes=None,
        message="Driver unavailable",
        created_by="staff_jane",
    )

    bob_notifs = notification_service.get_user_notifications(db, "user_bob")
    assert len(bob_notifs) == 1
    msg = bob_notifs[0].message
    assert "Route 2 at Library: cancelled" in msg
    assert "Reason: Driver unavailable" in msg


def test_resolved_notification_message(db):
    r1 = db.query(Route).filter_by(name="Route 2").first()
    s1 = db.query(Stop).filter_by(name="Library").first()
    t1 = db.query(Trip).filter_by(route_id=r1.id).first()

    sub = Subscription(user_ref="user_dave", route_id=r1.id, stop_id=s1.id)
    db.add(sub)
    db.commit()

    # First report a breakdown
    incident_service.report_incident(
        db=db,
        trip_id=t1.id,
        type=IncidentType.BREAKDOWN,
        delay_minutes=None,
        message="Engine stalling",
        created_by="staff_jane",
    )

    # Then resolve it
    incident_service.report_incident(
        db=db,
        trip_id=t1.id,
        type=IncidentType.RESOLVED,
        delay_minutes=None,
        message="Replacement shuttle dispatched",
        created_by="staff_jane",
    )

    dave_notifs = notification_service.get_user_notifications(db, "user_dave")
    assert len(dave_notifs) == 2
    # Newest first
    resolved_msg = dave_notifs[0].message
    assert "Route 2 at Library: back on schedule" in resolved_msg
    assert "Reason: Replacement shuttle dispatched" in resolved_msg


def test_one_failing_subscription_does_not_stop_others(db, monkeypatch):
    r1 = db.query(Route).filter_by(name="Route 2").first()
    s1 = db.query(Stop).filter_by(name="Library").first()
    s2 = db.query(Stop).filter_by(name="Student Center").first()
    t1 = db.query(Trip).filter_by(route_id=r1.id).first()

    sub1 = Subscription(user_ref="user_err", route_id=r1.id, stop_id=s1.id)
    sub2 = Subscription(user_ref="user_ok", route_id=r1.id, stop_id=s2.id)
    db.add_all([sub1, sub2])
    db.commit()

    original_build_message = notification_service.build_notification_message

    def flaky_build_message(route, stop, incident, eta_dt):
        if stop and stop.id == s1.id:
            raise RuntimeError("Database simulation error on subscriber 1")
        return original_build_message(route, stop, incident, eta_dt)

    monkeypatch.setattr(notification_service, "build_notification_message", flaky_build_message)

    incident_service.report_incident(
        db=db,
        trip_id=t1.id,
        type=IncidentType.DELAY,
        delay_minutes=10,
        message="Minor slowdown",
        created_by="staff_dan",
    )

    err_notifs = notification_service.get_user_notifications(db, "user_err")
    ok_notifs = notification_service.get_user_notifications(db, "user_ok")

    # Sub 1 errored, but sub 2 still succeeded and received notification
    assert len(err_notifs) == 0
    assert len(ok_notifs) == 1
    assert "Student Center" in ok_notifs[0].message
