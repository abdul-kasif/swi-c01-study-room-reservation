from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from datetime import datetime, timedelta
from typing import Literal

SQLALCHEMY_DATABASE_URL = "sqlite:///./reservation.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Reservation(Base):
    __tablename__ = "reservations"
    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(String, index=True)
    user_id = Column(String, index=True)
    start_time = Column(DateTime, index=True)
    end_time = Column(DateTime)
    # States: DRAFT, PENDING_APPROVAL, CONFIRMED, CANCELLED
    state = Column(String)


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Study Room Reservation API - v0.2")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Mock External Boundary: Notification Service
class NotificationService:
    @staticmethod
    def notify(user_id: str, message: str):
        # Synchronous stub simulating < 2s external boundary response
        print(f"[NotificationService] To {user_id}: {message}")


class ReservationCreate(BaseModel):
    resource_id: str
    user_id: str
    start_time: datetime
    end_time: datetime


class AvailabilityCheck(BaseModel):
    resource_id: str
    start_time: datetime
    end_time: datetime


class ApprovalDecision(BaseModel):
    admin_id: str
    decision: Literal["approve", "reject"]


def requires_approval(resource_id: str) -> bool:
    """Rooms prefixed with 'VIP_' require explicit administrator approval."""
    return resource_id.startswith("VIP_")


# OP-01: Create Reservation
@app.post("/reservations")
def create_reservation(req: ReservationCreate, db: Session = Depends(get_db)):
    if req.start_time >= req.end_time:
        raise HTTPException(
            status_code=400,
            detail="Invalid interval: start time must be before end time",
        )

    day_start = req.start_time.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    # BR-04: Active states (DRAFT, PENDING_APPROVAL, CONFIRMED) count toward 4-hour daily limit
    user_reservations = (
        db.query(Reservation)
        .filter(
            Reservation.user_id == req.user_id,
            Reservation.start_time >= day_start,
            Reservation.start_time < day_end,
            Reservation.state != "CANCELLED",
        )
        .all()
    )

    total_seconds = sum(
        (r.end_time - r.start_time).total_seconds() for r in user_reservations
    )
    new_duration = (req.end_time - req.start_time).total_seconds()

    if (total_seconds + new_duration) > 4 * 3600:
        raise HTTPException(
            status_code=400, detail="Domain Rule Violation: 4-hour daily limit exceeded"
        )

    new_res = Reservation(
        resource_id=req.resource_id,
        user_id=req.user_id,
        start_time=req.start_time,
        end_time=req.end_time,
        state="DRAFT",
    )
    db.add(new_res)
    db.commit()
    db.refresh(new_res)
    return {"id": new_res.id, "state": new_res.state}


# OP-02: Check Availability
@app.post("/availability")
def check_availability(req: AvailabilityCheck, db: Session = Depends(get_db)):
    if req.start_time >= req.end_time:
        raise HTTPException(
            status_code=400,
            detail="Invalid interval: start time must be before end time",
        )

    overlap = (
        db.query(Reservation)
        .filter(
            Reservation.resource_id == req.resource_id,
            Reservation.state == "CONFIRMED",
            Reservation.start_time < req.end_time,
            Reservation.end_time > req.start_time,
        )
        .first()
    )

    if overlap:
        return {"status": "UNAVAILABLE"}
    return {"status": "AVAILABLE"}


# OP-03: Confirm Reservation
@app.post("/reservations/{reservation_id}/confirm")
def confirm_reservation(reservation_id: int, db: Session = Depends(get_db)):
    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if res.state != "DRAFT":
        raise HTTPException(
            status_code=400, detail="Only DRAFT reservations can be confirmed"
        )

    overlap = (
        db.query(Reservation)
        .filter(
            Reservation.resource_id == res.resource_id,
            Reservation.state == "CONFIRMED",
            Reservation.start_time < res.end_time,
            Reservation.end_time > res.start_time,
            Reservation.id != res.id,
        )
        .first()
    )

    if overlap:
        raise HTTPException(
            status_code=409,
            detail="Conflict: Resource was already booked by another user",
        )

    # Baseline v0.2 Change: Check if resource requires Administrator approval
    if requires_approval(res.resource_id):
        res.state = "PENDING_APPROVAL"
        db.commit()
        NotificationService.notify(
            res.user_id, f"Reservation {res.id} is pending administrator approval."
        )
        return {"id": res.id, "state": res.state}

    res.state = "CONFIRMED"
    db.commit()
    NotificationService.notify(res.user_id, f"Reservation {res.id} confirmed.")
    return {"id": res.id, "state": res.state}


# OP-05: Approve / Reject Reservation (Baseline v0.2)
@app.post("/reservations/{reservation_id}/approval")
def approve_or_reject_reservation(
    reservation_id: int, req: ApprovalDecision, db: Session = Depends(get_db)
):
    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if res.state != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=400,
            detail="Only PENDING_APPROVAL reservations can be approved or rejected",
        )

    # Handle rejection
    if req.decision == "reject":
        res.state = "CANCELLED"
        db.commit()
        NotificationService.notify(
            res.user_id,
            f"Reservation {res.id} was rejected by Administrator {req.admin_id}.",
        )
        return {"id": res.id, "state": res.state}

    # Handle expiration before approval
    if datetime.now() >= res.start_time:
        res.state = "CANCELLED"
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Approval expired: Start time has already passed; state set to CANCELLED",
        )

    # BR-02: Verify no other reservation was CONFIRMED while waiting for approval
    overlap = (
        db.query(Reservation)
        .filter(
            Reservation.resource_id == res.resource_id,
            Reservation.state == "CONFIRMED",
            Reservation.start_time < res.end_time,
            Reservation.end_time > res.start_time,
            Reservation.id != res.id,
        )
        .first()
    )

    if overlap:
        raise HTTPException(
            status_code=409,
            detail="Conflict: Resource was already confirmed for an overlapping slot",
        )

    res.state = "CONFIRMED"
    db.commit()
    NotificationService.notify(
        res.user_id,
        f"Reservation {res.id} was approved by Administrator {req.admin_id}.",
    )
    return {"id": res.id, "state": res.state}


# OP-04: Cancel Reservation
@app.post("/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: int, db: Session = Depends(get_db)):
    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    # Idempotent handling for already cancelled reservations
    if res.state == "CANCELLED":
        return {"id": res.id, "state": res.state}

    if datetime.now() >= res.start_time:
        raise HTTPException(
            status_code=400,
            detail="Policy Violation: Cannot cancel after the start time",
        )

    res.state = "CANCELLED"
    db.commit()
    NotificationService.notify(res.user_id, f"Reservation {res.id} has been cancelled.")
    return {"id": res.id, "state": res.state}
