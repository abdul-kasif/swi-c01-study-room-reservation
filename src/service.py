import logging
from datetime import datetime, timedelta
from src.domain import (
    BookingPolicy,
    InvalidStateTransitionError,
    ReservationConflictError,
    ReservationEntity,
    ReservationNotFoundError,
    ResourceNotFoundError,
)
from src.notifications import NotificationGateway
from src.repository import ReservationRepository

logger = logging.getLogger(__name__)


class ReservationService:
    def __init__(self, repo: ReservationRepository, notifier: NotificationGateway):
        self.repo = repo
        self.notifier = notifier

    # ------------------------------------------------------------------
    # C05 helpers (confirmation & approval unit)
    # ------------------------------------------------------------------
    def _notify_safely(self, *args, **kwargs) -> None:
        """Notify AFTER commit; a failing notification never undoes or hides
        a committed state change (ADR-01 failure-isolation decision)."""
        try:
            self.notifier.notify_state_change(*args, **kwargs)
        except Exception:
            logger.exception("Notification failed after state was committed")

    def _commit_transition(
        self,
        reservation_id: int,
        expected_state: str,
        new_state: str,
        enforce_no_overlap: bool,
    ) -> ReservationEntity:
        """Authoritative write: atomic compare-and-set via the repository.

        If it loses a race, classify why: state moved under us (400) or an
        overlapping CONFIRMED reservation appeared (409)."""
        applied = self.repo.try_transition(
            reservation_id, expected_state, new_state, enforce_no_overlap
        )
        current = self.repo.get_by_id(reservation_id)
        if current is None:
            raise ReservationNotFoundError("Reservation not found")
        if applied:
            return current
        if current.state != expected_state:
            raise InvalidStateTransitionError(
                "Reservation state changed concurrently; please retry"
            )
        raise ReservationConflictError(
            "Conflict: Resource was already booked by another user"
        )

    # ------------------------------------------------------------------
    def create_reservation(
        self, resource_id: str, user_id: str, start_time: datetime, end_time: datetime
    ) -> ReservationEntity:

        resource = self.repo.get_resource(resource_id)
        if not resource or not resource.is_active:
            raise ResourceNotFoundError(
                f"Resource '{resource_id}' does not exist or is inactive"
            )

        BookingPolicy.validate_interval(start_time, end_time)

        day_start = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        existing = self.repo.get_active_for_user_on_day(user_id, day_start, day_end)

        BookingPolicy.validate_daily_quota(existing, start_time, end_time)

        draft = ReservationEntity(
            id=None,
            resource_id=resource_id,
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            state="DRAFT",
        )
        return self.repo.create(draft)

    def check_availability(
        self, resource_id: str, start_time: datetime, end_time: datetime
    ) -> str:
        resource = self.repo.get_resource(resource_id)
        if not resource or not resource.is_active:
            raise ResourceNotFoundError(
                f"Resource '{resource_id}' does not exist or is inactive"
            )
        BookingPolicy.validate_interval(start_time, end_time)
        has_overlap = self.repo.has_confirmed_overlap(resource_id, start_time, end_time)
        return "UNAVAILABLE" if has_overlap else "AVAILABLE"

    def confirm_reservation(
        self, reservation_id: int, now: datetime | None = None
    ) -> ReservationEntity:
        if now is None:
            now = datetime.now()

        res = self.repo.get_by_id(reservation_id)
        if not res:
            raise ReservationNotFoundError("Reservation not found")

        res.ensure_can_confirm()

        if now >= res.start_time:
            raise InvalidStateTransitionError(
                "Cannot confirm a reservation in the past"
            )

        has_conflict = self.repo.has_confirmed_overlap(
            res.resource_id, res.start_time, res.end_time, exclude_id=res.id
        )
        needs_approval = BookingPolicy.requires_admin_approval(res.resource_id)
        res.confirm(has_conflict=has_conflict, requires_approval=needs_approval)

        saved = self._commit_transition(
            res.id, "DRAFT", res.state, enforce_no_overlap=True
        )
        self._notify_safely(saved.user_id, saved.id, saved.state)
        return saved

    def process_approval(
        self, reservation_id: int, admin_id: str, decision: str, now: datetime
    ) -> ReservationEntity:
        res = self.repo.get_by_id(reservation_id)
        if not res:
            raise ReservationNotFoundError("Reservation not found")

        res.ensure_can_process_approval()

        if decision == "reject":
            res.reject()
            saved = self._commit_transition(
                res.id, "PENDING_APPROVAL", res.state, enforce_no_overlap=False
            )
            self._notify_safely(saved.user_id, saved.id, saved.state, admin_id=admin_id)
            return saved

        if res.is_expired(now):
            res.mark_expired()
            self._commit_transition(
                res.id, "PENDING_APPROVAL", res.state, enforce_no_overlap=False
            )
            raise InvalidStateTransitionError(
                "Approval expired: Start time has already passed; state set to CANCELLED"
            )

        has_conflict = self.repo.has_confirmed_overlap(
            res.resource_id, res.start_time, res.end_time, exclude_id=res.id
        )
        res.approve(has_conflict=has_conflict)
        saved = self._commit_transition(
            res.id, "PENDING_APPROVAL", res.state, enforce_no_overlap=True
        )
        self._notify_safely(saved.user_id, saved.id, saved.state, admin_id=admin_id)
        return saved

    def cancel_reservation(
        self, reservation_id: int, now: datetime
    ) -> ReservationEntity:
        res = self.repo.get_by_id(reservation_id)
        if not res:
            raise ReservationNotFoundError("Reservation not found")

        if res.state == "CANCELLED":
            return res

        res.ensure_can_cancel(now)
        saved = self._commit_transition(
            res.id, res.state, "CANCELLED", enforce_no_overlap=False
        )
        self._notify_safely(saved.user_id, saved.id, saved.state)
        return saved

    def cleanup_expired_reservations(self, now: datetime) -> int:
        """Cancel all stale DRAFT and PENDING_APPROVAL reservations."""
        return self.repo.cleanup_expired(now)
