from datetime import datetime, timezone
from typing import Optional, Sequence
from sqlalchemy.orm import Session

from app.models import Incident, IncidentType, Trip, TripStatus
from app.services.notification_service import notify_affected


def report_incident(
    db: Session,
    trip_id: int,
    type: IncidentType | str,
    delay_minutes: Optional[int],
    message: str,
    created_by: str,
    now: Optional[datetime] = None,
) -> Incident:
    """
    Reports a transit disruption incident for a trip.
    Deactivates previous active incidents on the trip, sets the trip status,
    validates the inputs, and stores the incident for auditing.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Validate type
    if isinstance(type, str):
        try:
            incident_type = IncidentType(type.upper())
        except ValueError:
            raise ValueError(f"Invalid incident type: {type}")
    else:
        incident_type = type

    # Validate trip existence
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise ValueError(f"Trip with id {trip_id} not found")

    # Validate DELAY constraints
    if incident_type == IncidentType.DELAY:
        if delay_minutes is None or delay_minutes <= 0:
            raise ValueError("DELAY incident requires delay_minutes > 0")

    # Deactivate previous active incidents for this trip
    active_incidents = (
        db.query(Incident)
        .filter(Incident.trip_id == trip_id, Incident.is_active.is_(True))
        .all()
    )
    for inc in active_incidents:
        inc.is_active = False

    # Update trip status and determine if this new incident is active
    if incident_type == IncidentType.RESOLVED:
        trip.status = TripStatus.SCHEDULED
        is_active = False
    elif incident_type == IncidentType.DELAY:
        trip.status = TripStatus.DELAYED
        is_active = True
    elif incident_type == IncidentType.BREAKDOWN:
        trip.status = TripStatus.BROKEN_DOWN
        is_active = True
    elif incident_type == IncidentType.CANCELLATION:
        trip.status = TripStatus.CANCELLED
        is_active = True
    else:
        is_active = True

    incident = Incident(
        trip_id=trip_id,
        type=incident_type,
        delay_minutes=delay_minutes if incident_type == IncidentType.DELAY else None,
        message=message,
        created_by=created_by,
        created_at=now,
        is_active=is_active,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    db.refresh(trip)

    # Notify all affected subscribers for this trip
    notify_affected(db, incident, now=now)

    return incident


def history(db: Session, trip_id: int) -> Sequence[Incident]:
    """
    Returns full incident history for a trip, newest first.
    """
    return (
        db.query(Incident)
        .filter(Incident.trip_id == trip_id)
        .order_by(Incident.created_at.desc(), Incident.id.desc())
        .all()
    )

