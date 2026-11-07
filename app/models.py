from datetime import datetime, timezone
import enum
from typing import Optional, List

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TripStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    BROKEN_DOWN = "BROKEN_DOWN"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class IncidentType(str, enum.Enum):
    DELAY = "DELAY"
    BREAKDOWN = "BREAKDOWN"
    CANCELLATION = "CANCELLATION"
    RESOLVED = "RESOLVED"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    route_stops: Mapped[List["RouteStop"]] = relationship(
        "RouteStop", back_populates="route", cascade="all, delete-orphan", order_by="RouteStop.sequence"
    )
    trips: Mapped[List["Trip"]] = relationship(
        "Trip", back_populates="route", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[List["Subscription"]] = relationship(
        "Subscription", back_populates="route", cascade="all, delete-orphan"
    )


class Stop(Base):
    __tablename__ = "stops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    route_stops: Mapped[List["RouteStop"]] = relationship(
        "RouteStop", back_populates="stop", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[List["Subscription"]] = relationship(
        "Subscription", back_populates="stop", cascade="all, delete-orphan"
    )


class RouteStop(Base):
    __tablename__ = "route_stops"
    __table_args__ = (
        UniqueConstraint("route_id", "sequence", name="uq_route_sequence"),
        UniqueConstraint("route_id", "stop_id", name="uq_route_stop"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), nullable=False)
    stop_id: Mapped[int] = mapped_column(ForeignKey("stops.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    route: Mapped["Route"] = relationship("Route", back_populates="route_stops")
    stop: Mapped["Stop"] = relationship("Stop", back_populates="route_stops")


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), nullable=False, index=True)
    scheduled_departure: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[TripStatus] = mapped_column(
        Enum(TripStatus, native_enum=False),
        nullable=False,
        default=TripStatus.SCHEDULED,
        index=True,
    )

    route: Mapped["Route"] = relationship("Route", back_populates="trips")
    incidents: Mapped[List["Incident"]] = relationship(
        "Incident", back_populates="trip", cascade="all, delete-orphan", order_by="Incident.created_at.desc()"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification", back_populates="trip", cascade="all, delete-orphan"
    )


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), nullable=False, index=True)
    type: Mapped[IncidentType] = mapped_column(
        Enum(IncidentType, native_enum=False), nullable=False
    )
    delay_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="incidents")


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_ref", "route_id", "stop_id", name="uq_user_route_stop"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_ref: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), nullable=False)
    stop_id: Mapped[int] = mapped_column(ForeignKey("stops.id"), nullable=False)

    route: Mapped["Route"] = relationship("Route", back_populates="subscriptions")
    stop: Mapped["Stop"] = relationship("Stop", back_populates="subscriptions")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_ref: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    trip: Mapped["Trip"] = relationship("Trip", back_populates="notifications")
