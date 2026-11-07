from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from sqlalchemy.orm import Session

from app.config import STALE_THRESHOLD_MINUTES
from app.models import Incident, IncidentType, RouteStop, Stop, Trip, TripStatus


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stop_status(
    trip: Trip,
    route_stop: RouteStop,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Computes stop arrival status and ETA for a given trip and route_stop.
    Returns:
        dict with keys:
        scheduled_time, estimated_time, delay_minutes, status, message, last_updated, is_stale
    """
    if now is None:
        now = datetime.now(timezone.utc)

    now_utc = _ensure_utc(now)
    departure_utc = _ensure_utc(trip.scheduled_departure)
    offset = getattr(route_stop, "offset_minutes", 0)
    scheduled_time = departure_utc + timedelta(minutes=offset)

    # Find the active incident for this trip, if any
    incidents = getattr(trip, "incidents", []) or []
    active_incident: Optional[Incident] = next(
        (inc for inc in incidents if inc.is_active), None
    )

    if not active_incident:
        return {
            "scheduled_time": scheduled_time,
            "estimated_time": scheduled_time,
            "delay_minutes": 0,
            "status": "ON_TIME",
            "message": None,
            "last_updated": None,
            "is_stale": False,
        }

    created_at_utc = _ensure_utc(active_incident.created_at)
    time_diff = (now_utc - created_at_utc).total_seconds() if (now_utc and created_at_utc) else 0
    is_stale = time_diff > (STALE_THRESHOLD_MINUTES * 60)

    inc_type = active_incident.type
    if isinstance(inc_type, str):
        inc_type = IncidentType(inc_type)

    if inc_type == IncidentType.DELAY:
        delay_min = active_incident.delay_minutes or 0
        return {
            "scheduled_time": scheduled_time,
            "estimated_time": scheduled_time + timedelta(minutes=delay_min),
            "delay_minutes": delay_min,
            "status": TripStatus.DELAYED.value,
            "message": active_incident.message,
            "last_updated": created_at_utc,
            "is_stale": is_stale,
        }

    elif inc_type == IncidentType.BREAKDOWN:
        return {
            "scheduled_time": scheduled_time,
            "estimated_time": None,
            "delay_minutes": active_incident.delay_minutes or 0,
            "status": TripStatus.BROKEN_DOWN.value,
            "message": active_incident.message,
            "last_updated": created_at_utc,
            "is_stale": is_stale,
        }

    elif inc_type == IncidentType.CANCELLATION:
        return {
            "scheduled_time": scheduled_time,
            "estimated_time": None,
            "delay_minutes": 0,
            "status": TripStatus.CANCELLED.value,
            "message": active_incident.message,
            "last_updated": created_at_utc,
            "is_stale": is_stale,
        }

    else:
        # Fallback for unexpected or resolved incident marked active
        return {
            "scheduled_time": scheduled_time,
            "estimated_time": scheduled_time,
            "delay_minutes": 0,
            "status": "ON_TIME",
            "message": active_incident.message,
            "last_updated": created_at_utc,
            "is_stale": is_stale,
        }


def get_stop_arrivals(
    db: Session,
    stop_id: int,
    now: Optional[datetime] = None,
    window_hours: int = 3,
) -> Optional[list[dict[str, Any]]]:
    """
    Finds upcoming trips (next `window_hours` hours) serving the given stop,
    computes real-time ETAs and disruption status for each.
    Returns None if stop does not exist.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    now_utc = _ensure_utc(now)
    stop = db.query(Stop).filter(Stop.id == stop_id).first()
    if not stop:
        return None

    route_stops = (
        db.query(RouteStop)
        .filter(RouteStop.stop_id == stop_id)
        .all()
    )
    if not route_stops:
        return []

    arrivals = []
    window_end = now_utc + timedelta(hours=window_hours)

    for rs in route_stops:
        trips = (
            db.query(Trip)
            .filter(Trip.route_id == rs.route_id)
            .all()
        )
        for trip in trips:
            status = stop_status(trip, rs, now=now)
            sched = _ensure_utc(status["scheduled_time"])
            est = _ensure_utc(status["estimated_time"]) if status["estimated_time"] else sched

            # Include if departure/arrival falls within upcoming window
            if sched and (now_utc - timedelta(minutes=15) <= est <= window_end or now_utc - timedelta(minutes=15) <= sched <= window_end):
                arrivals.append({
                    "trip_id": trip.id,
                    "route_id": trip.route_id,
                    "route_name": trip.route.name if trip.route else f"Route {trip.route_id}",
                    "stop_id": stop.id,
                    "stop_name": stop.name,
                    "scheduled_time": status["scheduled_time"],
                    "estimated_time": status["estimated_time"],
                    "delay_minutes": status["delay_minutes"],
                    "status": status["status"],
                    "message": status["message"],
                    "last_updated": status["last_updated"],
                    "is_stale": status["is_stale"],
                })

    arrivals.sort(key=lambda a: a["estimated_time"] or a["scheduled_time"])
    return arrivals
