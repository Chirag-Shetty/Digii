from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Route, Stop
from app.schemas import (
    ArrivalResponse,
    NotificationResponse,
    RouteResponse,
    StopResponse,
    SubscriptionCreate,
    SubscriptionResponse,
)
from app.services import eta_service, notification_service

router = APIRouter(prefix="/api", tags=["rider"])


@router.get("/routes", response_model=List[RouteResponse])
def get_routes(db: Session = Depends(get_db)):
    """
    Returns all campus transit routes and their stops.
    """
    return db.query(Route).all()


@router.get("/stops", response_model=List[StopResponse])
def get_stops(db: Session = Depends(get_db)):
    """
    Returns all campus stops ordered alphabetically.
    """
    return db.query(Stop).order_by(Stop.name).all()


@router.get("/stops/{stop_id}/arrivals", response_model=List[ArrivalResponse])
def get_stop_arrivals(
    stop_id: int,
    now: Optional[datetime] = None,
    db: Session = Depends(get_db),
):
    """
    Returns upcoming trip arrivals (next 3 hours) for a stop with computed ETAs,
    delays, disruption reasons, and staleness flags. Supports injectable `now` query.
    """
    arrivals = eta_service.get_stop_arrivals(db, stop_id, now=now)
    if arrivals is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stop with id {stop_id} not found",
        )
    return arrivals


@router.post(
    "/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def subscribe(payload: SubscriptionCreate, db: Session = Depends(get_db)):
    """
    Subscribes a rider to disruption notifications for a specific route and stop.
    """
    try:
        sub = notification_service.create_subscription(
            db=db,
            user_ref=payload.user_ref,
            route_id=payload.route_id,
            stop_id=payload.stop_id,
        )
        return sub
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)


@router.delete("/subscriptions/{id}", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(id: int, db: Session = Depends(get_db)):
    """
    Removes a rider subscription.
    """
    success = notification_service.delete_subscription(db, id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription with id {id} not found",
        )
    return None


@router.get("/inbox/{user_ref}", response_model=List[NotificationResponse])
def get_user_inbox(user_ref: str, db: Session = Depends(get_db)):
    """
    Returns all notifications sent to a rider, newest first.
    """
    return notification_service.get_user_notifications(db, user_ref)
