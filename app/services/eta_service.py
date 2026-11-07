from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.config import STALE_THRESHOLD_MINUTES
from app.models import Incident, IncidentType, RouteStop, Trip, TripStatus


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
