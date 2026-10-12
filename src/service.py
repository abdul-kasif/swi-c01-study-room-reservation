from datetime import datetime, timedelta
from src.domain import (
    BookingPolicy,
    InvalidStateTransitionError,
    ReservationEntity,
    ReservationNotFoundError,
)
from src.notifications import NotificationGateway
from src.repository import ReservationRepository


class ReservationService:
    def __init__(self, repo: ReservationRepository, notifier: NotificationGateway):
        self.repo = repo
        self.notifier = notifier

    def create_reservation(
        self, resource_id: str, user_id: str, start_time: datetime, end_time: datetime
    ) -> ReservationEntity:
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
        BookingPolicy.validate_interval(start_time, end_time)
        has_overlap = self.repo.has_confirmed_overlap(resource_id, start_time, end_time)
        return "UNAVAILABLE" if has_overlap else "AVAILABLE"

    def confirm_reservation(self, reservation_id: int) -> ReservationEntity:
        res = self.repo.get_by_id(reservation_id)
        if not res:
            raise ReservationNotFoundError("Reservation not found")

        res.ensure_can_confirm()
        has_conflict = self.repo.has_confirmed_overlap(
            res.resource_id, res.start_time, res.end_time, exclude_id=res.id
        )
        needs_approval = BookingPolicy.requires_admin_approval(res.resource_id)

        res.confirm(has_conflict=has_conflict, requires_approval=needs_approval)
        saved = self.repo.save(res)
        self.notifier.notify_state_change(saved.user_id, saved.id, saved.state)
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
            saved = self.repo.save(res)
            self.notifier.notify_state_change(
                saved.user_id, saved.id, saved.state, admin_id=admin_id
            )
            return saved

        if res.is_expired(now):
            res.mark_expired()
            self.repo.save(res)
            raise InvalidStateTransitionError(
                "Approval expired: Start time has already passed; state set to CANCELLED"
            )

        has_conflict = self.repo.has_confirmed_overlap(
            res.resource_id, res.start_time, res.end_time, exclude_id=res.id
        )
        res.approve(has_conflict=has_conflict)
        saved = self.repo.save(res)
        self.notifier.notify_state_change(
            saved.user_id, saved.id, saved.state, admin_id=admin_id
        )
        return saved

    def cancel_reservation(
        self, reservation_id: int, now: datetime
    ) -> ReservationEntity:
        res = self.repo.get_by_id(reservation_id)
        if not res:
            raise ReservationNotFoundError("Reservation not found")

        changed = res.cancel(now)
        if changed:
            res = self.repo.save(res)
            self.notifier.notify_state_change(res.user_id, res.id, res.state)
        return res
