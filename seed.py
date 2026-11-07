from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models import (
    Incident,
    IncidentType,
    Notification,
    Route,
    RouteStop,
    Stop,
    Subscription,
    Trip,
    TripStatus,
)


def seed_data(db: Session, base_time: datetime | None = None) -> None:
    if base_time is None:
        base_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    # 1. Stops (6 stops)
    stop_names = [
        "Main Quad",
        "Science & Engineering Hall",
        "University Library",
        "North Residential Village",
        "Student Activity Center",
        "South Campus Stadium",
    ]
    stops: dict[str, Stop] = {}
    for name in stop_names:
        stop = db.query(Stop).filter_by(name=name).first()
        if not stop:
            stop = Stop(name=name)
            db.add(stop)
            db.flush()
        stops[name] = stop

    # 2. Routes (2 routes)
    routes_config = [
        {
            "name": "North Express (Route Red)",
            "stops": [
                ("Main Quad", 0),
                ("Science & Engineering Hall", 8),
                ("University Library", 16),
                ("North Residential Village", 25),
            ],
        },
        {
            "name": "South Campus Loop (Route Blue)",
            "stops": [
                ("Main Quad", 0),
                ("University Library", 7),
                ("Student Activity Center", 15),
                ("South Campus Stadium", 24),
            ],
        },
    ]

    routes: dict[str, Route] = {}
    for r_data in routes_config:
        route = db.query(Route).filter_by(name=r_data["name"]).first()
        if not route:
            route = Route(name=r_data["name"])
            db.add(route)
            db.flush()
        routes[r_data["name"]] = route

        # Ensure RouteStops
        for seq, (s_name, offset) in enumerate(r_data["stops"], start=1):
            target_stop = stops[s_name]
            rs = (
                db.query(RouteStop)
                .filter_by(route_id=route.id, stop_id=target_stop.id)
                .first()
            )
            if not rs:
                rs = RouteStop(
                    route_id=route.id,
                    stop_id=target_stop.id,
                    sequence=seq,
                    offset_minutes=offset,
                )
                db.add(rs)
            else:
                rs.sequence = seq
                rs.offset_minutes = offset

    db.flush()

    # 3. Trips for next 24 hours (departures every 60 minutes for each route)
    for route in routes.values():
        for hour in range(24):
            dept_time = base_time + timedelta(hours=hour)
            existing = (
                db.query(Trip)
                .filter_by(route_id=route.id, scheduled_departure=dept_time)
                .first()
            )
            if not existing:
                trip = Trip(
                    route_id=route.id,
                    scheduled_departure=dept_time,
                    status=TripStatus.SCHEDULED,
                )
                db.add(trip)

    db.flush()

    # 4. Demo Subscriptions (3 subscriptions)
    demo_subscriptions = [
        ("user_alice", "North Express (Route Red)", "Science & Engineering Hall"),
        ("user_bob", "North Express (Route Red)", "North Residential Village"),
        ("user_charlie", "South Campus Loop (Route Blue)", "Student Activity Center"),
    ]

    for user_ref, route_name, stop_name in demo_subscriptions:
        r = routes[route_name]
        s = stops[stop_name]
        sub = (
            db.query(Subscription)
            .filter_by(user_ref=user_ref, route_id=r.id, stop_id=s.id)
            .first()
        )
        if not sub:
            sub = Subscription(user_ref=user_ref, route_id=r.id, stop_id=s.id)
            db.add(sub)

    db.commit()
    print("Seeding completed successfully.")


if __name__ == "__main__":
    init_db()
    with SessionLocal() as session:
        seed_data(session)

