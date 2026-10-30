import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.domain import (
    DailyQuotaExceededError,
    InvalidIntervalError,
    InvalidStateTransitionError,
    ReservationConflictError,
    ReservationNotFoundError,
    ResourceNotFoundError,
)
from src.notifications import NotificationGateway
from src.repository import Base, engine, ReservationRepository, SessionLocal
from src.service import ReservationService

load_dotenv()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Study Room Reservation API - v0.3 Architecture")

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


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
    if isinstance(exc, ResourceNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ReservationConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(
        exc,
        (InvalidIntervalError, DailyQuotaExceededError, InvalidStateTransitionError),
    ):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Internal server error")


def require_admin_auth(x_admin_token: str | None = Header(default=None)):
    """Dependency to enforce basic admin authorization."""
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(
            status_code=401, detail="Unauthorized: Invalid or missing admin token"
        )
    return True


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
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
        raise _translate_domain_error(exc)


@app.post("/reservations/{reservation_id}/confirm")
def confirm_reservation(
    reservation_id: int,
    service: ReservationService = Depends(get_reservation_service),
):
    try:
        res = service.confirm_reservation(reservation_id, now=datetime.now())
        return {"id": res.id, "state": res.state}
    except Exception as exc:  # noqa: BLE001
        raise _translate_domain_error(exc)


@app.post("/reservations/{reservation_id}/approval")
def approve_or_reject_reservation(
    reservation_id: int,
    req: ApprovalDecision,
    service: ReservationService = Depends(get_reservation_service),
    _: bool = Depends(require_admin_auth),
):
    try:
        res = service.process_approval(
            reservation_id=reservation_id,
            admin_id=req.admin_id,
            decision=req.decision,
            now=datetime.now(),
        )
        return {"id": res.id, "state": res.state}
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
        raise _translate_domain_error(exc)


@app.post("/admin/cleanup-expired")
def cleanup_expired_reservations(
    service: ReservationService = Depends(get_reservation_service),
    _: bool = Depends(require_admin_auth),
):
    count = service.cleanup_expired_reservations(now=datetime.now())
    return {"cancelled_count": count}


# =========================================================================
# UI ROUTES (Returns HTML for the Frontend)
# =========================================================================


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/student", response_class=HTMLResponse)
def student_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="student.html")


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="admin.html")


@app.post("/ui/reservations", response_class=HTMLResponse)
def create_reservation_ui(
    request: Request,
    resource_id: str = Form(...),
    user_id: str = Form(...),
    start_time: datetime = Form(...),
    end_time: datetime = Form(...),
    service: ReservationService = Depends(get_reservation_service),
):
    try:
        res = service.create_reservation(resource_id, user_id, start_time, end_time)
        return templates.TemplateResponse(
            request=request,
            name="partials/create_success.html",
            context={"res": res},
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="partials/error_alert.html",
            context={"error": str(exc)},
        )


@app.post("/ui/reservations/{reservation_id}/confirm", response_class=HTMLResponse)
def confirm_reservation_ui(
    request: Request,
    reservation_id: int,
    service: ReservationService = Depends(get_reservation_service),
):
    try:
        res = service.confirm_reservation(reservation_id, now=datetime.now())
        return templates.TemplateResponse(
            request=request, name="partials/reservation_row.html", context={"res": res}
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="partials/error_alert.html",
            context={"error": str(exc)},
        )


@app.post("/ui/reservations/{reservation_id}/cancel", response_class=HTMLResponse)
def cancel_reservation_ui(
    request: Request,
    reservation_id: int,
    service: ReservationService = Depends(get_reservation_service),
):
    try:
        res = service.cancel_reservation(reservation_id, now=datetime.now())
        return templates.TemplateResponse(
            request=request, name="partials/reservation_row.html", context={"res": res}
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="partials/error_alert.html",
            context={"error": str(exc)},
        )
