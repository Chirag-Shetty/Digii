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


class StopETA(BaseModel):
    stop_id: int
    stop_name: str
    sequence: int
    scheduled_time: datetime
    estimated_time: Optional[datetime] = None
    delay_minutes: int = 0
    status: str
    message: Optional[str] = None
    last_updated: Optional[datetime] = None
    is_stale: bool = False


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


class ResolveRequest(BaseModel):
    message: str = "Disruption resolved, back on schedule."
    created_by: str = "staff"


class StaffTripResponse(BaseModel):
    id: int
    route_id: int
    route_name: str
    scheduled_departure: datetime
    status: TripStatus
    active_incident: Optional[IncidentResponse] = None
    model_config = ConfigDict(from_attributes=True)


class StaffSummaryResponse(BaseModel):
    active_incidents: int
    total_notifications_sent: int
    estimated_calls_avoided: int


class TripDetailResponse(TripResponse):
    route_name: str
    stops: List[StopETA] = []
    active_incident: Optional[IncidentResponse] = None


class ArrivalResponse(BaseModel):
    trip_id: int
    route_id: int
    route_name: str
    stop_id: int
    stop_name: str
    scheduled_time: datetime
    estimated_time: Optional[datetime] = None
    delay_minutes: int = 0
    status: str
    message: Optional[str] = None
    last_updated: Optional[datetime] = None
    is_stale: bool = False


class TripDetailResponse(TripResponse):
    route_name: str
    stops: List[StopETA] = []
    active_incident: Optional[IncidentResponse] = None


class ArrivalResponse(BaseModel):
    trip_id: int
    route_id: int
    route_name: str
    stop_id: int
    stop_name: str
    scheduled_time: datetime
    estimated_time: Optional[datetime] = None
    delay_minutes: int = 0
    status: str
    message: Optional[str] = None
    last_updated: Optional[datetime] = None
    is_stale: bool = False


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
