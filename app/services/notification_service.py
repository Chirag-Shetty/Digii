from datetime import datetime, timezone
import logging
from typing import Optional, Sequence
from sqlalchemy.orm import Session

from app.models import Incident, IncidentType, Notification, Route, RouteStop, Stop, Subscription, Trip
from app.services import eta_service

logger = logging.getLogger(__name__)


def build_notification_message(
    route: Route,
    stop: Stop,
    incident: Incident,
    eta_dt: Optional[datetime],
) -> str:
    route_name = route.name if route else f"Route {incident.trip.route_id}"
    stop_name = stop.name if stop else "Stop"
    inc_type = incident.type
    if isinstance(inc_type, str):
        inc_type = IncidentType(inc_type)

    if inc_type == IncidentType.DELAY:
        delay = incident.delay_minutes or 0
        if eta_dt:
            eta_str = f"{eta_dt.hour}:{eta_dt.minute:02d}"
        else:
            eta_str = "TBD"
        return f"{route_name} at {stop_name}: delayed {delay} min, new ETA {eta_str}. Reason: {incident.message}"
    elif inc_type == IncidentType.CANCELLATION:
        return f"{route_name} at {stop_name}: cancelled. Reason: {incident.message}"
    elif inc_type == IncidentType.BREAKDOWN:
        return f"{route_name} at {stop_name}: broken down. Reason: {incident.message}"
    elif inc_type == IncidentType.RESOLVED:
        return f"{route_name} at {stop_name}: back on schedule. Reason: {incident.message}"
    else:
        return f"{route_name} at {stop_name}: update - {incident.message}"


def notify_affected(
    db: Session,
    incident: Incident,
    now: Optional[datetime] = None,
) -> list[Notification]:
    """
    Finds subscriptions affected by an incident on a trip,
    generates contextual human-readable alert messages with ETA for each stop,
    persists a Notification record per subscription, and prints to console.
    Errors on individual subscriptions are logged without interrupting others.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    trip = db.query(Trip).filter(Trip.id == incident.trip_id).first()
    if not trip:
        logger.error(f"Trip {incident.trip_id} not found when notifying affected riders.")
        return []

    route = db.query(Route).filter(Route.id == trip.route_id).first()
    if not route:
        logger.error(f"Route {trip.route_id} not found when notifying affected riders.")
        return []

    # Map stop_id -> RouteStop for quick sequence/offset lookup
    route_stops = (
        db.query(RouteStop)
        .filter(RouteStop.route_id == trip.route_id)
        .all()
    )
    route_stops_by_stop_id = {rs.stop_id: rs for rs in route_stops}

    # For now: all stops on the route (sequence >= 1)
    first_affected_sequence = 1

    subscriptions = (
        db.query(Subscription)
        .filter(Subscription.route_id == trip.route_id)
        .all()
    )

    created_notifications: list[Notification] = []

    for sub in subscriptions:
        try:
            rs = route_stops_by_stop_id.get(sub.stop_id)
            if rs and rs.sequence < first_affected_sequence:
                continue

            # Calculate stop ETA
            eta_dt: Optional[datetime] = None
            if rs:
                status = eta_service.stop_status(trip, rs, now=now)
                eta_dt = status.get("estimated_time")

            stop = sub.stop or db.query(Stop).filter(Stop.id == sub.stop_id).first()
            msg = build_notification_message(route, stop, incident, eta_dt)

            notif = Notification(
                user_ref=sub.user_ref,
                trip_id=trip.id,
                message=msg,
                created_at=now,
            )
            db.add(notif)
            db.commit()
            db.refresh(notif)
            print(f"[NOTIFICATION] To {sub.user_ref}: {msg}")
            created_notifications.append(notif)

        except Exception as exc:
            logger.exception(f"Error notifying subscriber {getattr(sub, 'id', None)}: {exc}")
            db.rollback()

    return created_notifications


def create_subscription(
    db: Session,
    user_ref: str,
    route_id: int,
    stop_id: int,
) -> Subscription:
    """
    Creates or returns an existing subscription for a rider.
    Validates that route, stop, and route-stop relationship exist.
    """
    user_ref = user_ref.strip()
    if not user_ref:
        raise ValueError("user_ref must not be empty")

    route = db.query(Route).filter(Route.id == route_id).first()
    if not route:
        raise ValueError(f"Route with id {route_id} not found")

    stop = db.query(Stop).filter(Stop.id == stop_id).first()
    if not stop:
        raise ValueError(f"Stop with id {stop_id} not found")

    route_stop = (
        db.query(RouteStop)
        .filter(RouteStop.route_id == route_id, RouteStop.stop_id == stop_id)
        .first()
    )
    if not route_stop:
        raise ValueError(f"Stop {stop_id} does not belong to route {route_id}")

    existing = (
        db.query(Subscription)
        .filter(
            Subscription.user_ref == user_ref,
            Subscription.route_id == route_id,
            Subscription.stop_id == stop_id,
        )
        .first()
    )
    if existing:
        return existing

    sub = Subscription(user_ref=user_ref, route_id=route_id, stop_id=stop_id)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def get_user_notifications(db: Session, user_ref: str) -> Sequence[Notification]:
    """
    Returns notifications for a specific user, newest first.
    """
    return (
        db.query(Notification)
        .filter(Notification.user_ref == user_ref)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .all()
    )


def get_user_subscriptions(db: Session, user_ref: str) -> Sequence[Subscription]:
    """
    Returns active subscriptions for a specific user.
    """
    return (
        db.query(Subscription)
        .filter(Subscription.user_ref == user_ref)
        .all()
    )
