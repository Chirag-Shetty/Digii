from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict

from app.models import TripStatus, IncidentType


class StopBase(BaseModel):
    name: str


class StopResponse(StopBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class RouteStopResponse(BaseModel):
    stop_id: int
    sequence: int
    offset_minutes: int
    stop: Optional[StopResponse] = None
    model_config = ConfigDict(from_attributes=True)


class RouteBase(BaseModel):
    name: str


class RouteResponse(RouteBase):
    id: int
    route_stops: List[RouteStopResponse] = []
    model_config = ConfigDict(from_attributes=True)


class TripBase(BaseModel):
    route_id: int
    scheduled_departure: datetime
    status: TripStatus = TripStatus.SCHEDULED


class TripResponse(TripBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class IncidentBase(BaseModel):
    trip_id: int
    type: IncidentType
    delay_minutes: Optional[int] = None
    message: str
    created_by: str


class IncidentCreate(IncidentBase):
    pass


class IncidentResponse(IncidentBase):
    id: int
    created_at: datetime
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


class SubscriptionBase(BaseModel):
    user_ref: str
    route_id: int
    stop_id: int


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionResponse(SubscriptionBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class NotificationResponse(BaseModel):
    id: int
    user_ref: str
    trip_id: int
    message: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

