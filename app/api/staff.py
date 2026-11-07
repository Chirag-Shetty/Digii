from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_staff_key
from app.db import get_db
from app.models import IncidentType, Trip
from app.schemas import (
    IncidentCreate,
    IncidentResponse,
    ResolveRequest,
    StaffSummaryResponse,
    StaffTripResponse,
)
from app.services import incident_service

router = APIRouter(
    prefix="/api/staff",
    tags=["staff"],
    dependencies=[Depends(get_staff_key)],
)


@router.get("/trips", response_model=List[StaffTripResponse])
def get_staff_trips(db: Session = Depends(get_db)):
    """
    Returns upcoming trips with active incident information for staff dispatch view.
    """
    trips = db.query(Trip).order_by(Trip.scheduled_departure.asc()).all()
    results = []
    for trip in trips:
        active_inc = next((i for i in trip.incidents if i.is_active), None)
        results.append({
            "id": trip.id,
            "route_id": trip.route_id,
            "route_name": trip.route.name if trip.route else f"Route {trip.route_id}",
            "scheduled_departure": trip.scheduled_departure,
            "status": trip.status,
            "active_incident": active_inc,
        })
    return results


@router.post(
    "/incidents",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
)
def report_incident(payload: IncidentCreate, db: Session = Depends(get_db)):
    """
    Staff logs a transit incident once. System recalculates trip status/ETAs
    and automatically notifies all affected subscribers.
    """
    try:
        incident = incident_service.report_incident(
            db=db,
            trip_id=payload.trip_id,
            type=payload.type,
            delay_minutes=payload.delay_minutes,
            message=payload.message,
            created_by=payload.created_by,
        )
        return incident
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)


@router.post("/incidents/{trip_id}/resolve", response_model=IncidentResponse)
def resolve_trip_incident(
    trip_id: int,
    payload: Optional[ResolveRequest] = None,
    db: Session = Depends(get_db),
):
    """
    Resolves active disruption on a trip, restores trip status to SCHEDULED,
    and alerts riders that normal service is restored.
    """
    msg = payload.message if payload else "Disruption resolved, back on schedule."
    staff_name = payload.created_by if payload else "staff"

    try:
        incident = incident_service.report_incident(
            db=db,
            trip_id=trip_id,
            type=IncidentType.RESOLVED,
            delay_minutes=None,
            message=msg,
            created_by=staff_name,
        )
        return incident
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)


@router.get("/trips/{trip_id}/history", response_model=List[IncidentResponse])
def get_trip_incident_history(trip_id: int, db: Session = Depends(get_db)):
    """
    Returns the complete chronological audit trail of incidents for a trip (newest first).
    """
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trip with id {trip_id} not found",
        )
    return incident_service.history(db, trip_id)


@router.get("/summary", response_model=StaffSummaryResponse)
def get_summary(db: Session = Depends(get_db)):
    """
    Returns metric summary: active incident count and total notifications sent (calls avoided).
    """
    return incident_service.get_staff_summary(db)
