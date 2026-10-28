from datetime import datetime
from typing import Literal
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from src.domain import (
    DailyQuotaExceededError,
    InvalidIntervalError,
    InvalidStateTransitionError,
    ReservationConflictError,
    ReservationNotFoundError,
)
from src.notifications import NotificationGateway
from src.repository import Base, engine, SessionLocal, ReservationRepository
from src.service import ReservationService

app = FastAPI(title="Study Room Reservation API - v0.3 Architecture")


def get_reservation_service():
    db = SessionLocal()
    try:
        repo = ReservationRepository(db)
        notifier = NotificationGateway()
        yield ReservationService(repo=repo, notifier=notifier)
    finally:
        db.close()


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


def _translate_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ReservationNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ReservationConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(
        exc,
        (InvalidIntervalError, DailyQuotaExceededError, InvalidStateTransitionError),
    ):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Internal server error")


@app.post("/reservations")
def create_reservation(
    req: ReservationCreate,
    service: ReservationService = Depends(get_reservation_service),
):
    try:
        res = service.create_reservation(
            resource_id=req.resource_id,
            user_id=req.user_id,
            start_time=req.start_time,
            end_time=req.end_time,
        )
        return {"id": res.id, "state": res.state}
    except Exception as exc:
        raise _translate_domain_error(exc)


@app.post("/availability")
def check_availability(
    req: AvailabilityCheck,
    service: ReservationService = Depends(get_reservation_service),
):
    try:
        status = service.check_availability(
            resource_id=req.resource_id,
            start_time=req.start_time,
            end_time=req.end_time,
        )
        return {"status": status}
    except Exception as exc:
        raise _translate_domain_error(exc)


@app.post("/reservations/{reservation_id}/confirm")
def confirm_reservation(
    reservation_id: int,
    service: ReservationService = Depends(get_reservation_service),
):
    try:
        res = service.confirm_reservation(reservation_id, now=datetime.now())
        return {"id": res.id, "state": res.state}
    except Exception as exc:
        raise _translate_domain_error(exc)


@app.post("/reservations/{reservation_id}/approval")
def approve_or_reject_reservation(
    reservation_id: int,
    req: ApprovalDecision,
    service: ReservationService = Depends(get_reservation_service),
):
    try:
        res = service.process_approval(
            reservation_id=reservation_id,
            admin_id=req.admin_id,
            decision=req.decision,
            now=datetime.now(),
        )
        return {"id": res.id, "state": res.state}
    except Exception as exc:
        raise _translate_domain_error(exc)


@app.post("/reservations/{reservation_id}/cancel")
def cancel_reservation(
    reservation_id: int,
    service: ReservationService = Depends(get_reservation_service),
):
    try:
        res = service.cancel_reservation(
            reservation_id=reservation_id, now=datetime.now()
        )
        return {"id": res.id, "state": res.state}
    except Exception as exc:
        raise _translate_domain_error(exc)
