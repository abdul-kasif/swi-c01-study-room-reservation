from dataclasses import dataclass
from datetime import datetime


class DomainError(Exception):
    """Base class for domain-level exceptions."""


class InvalidIntervalError(DomainError):
    """Raised when BR-01 [start, end) interval semantics are violated."""


class DailyQuotaExceededError(DomainError):
    """Raised when BR-04 4-hour daily booking limit is exceeded."""


class ReservationNotFoundError(DomainError):
    """Raised when a requested reservation does not exist."""


class InvalidStateTransitionError(DomainError):
    """Raised when an operation is not allowed from the current lifecycle state."""


class ReservationConflictError(DomainError):
    """Raised when BR-02 exclusive resource invariant would be violated."""


@dataclass
class ReservationEntity:
    id: int | None
    resource_id: str
    user_id: str
    start_time: datetime
    end_time: datetime
    state: str = "DRAFT"

    def ensure_can_confirm(self) -> None:
        if self.state != "DRAFT":
            raise InvalidStateTransitionError(
                "Only DRAFT reservations can be confirmed"
            )

    def confirm(self, has_conflict: bool, requires_approval: bool) -> None:
        self.ensure_can_confirm()
        if has_conflict:
            raise ReservationConflictError(
                "Conflict: Resource was already booked by another user"
            )
        if requires_approval:
            self.state = "PENDING_APPROVAL"
        else:
            self.state = "CONFIRMED"

    def ensure_can_process_approval(self) -> None:
        if self.state != "PENDING_APPROVAL":
            raise InvalidStateTransitionError(
                "Only PENDING_APPROVAL reservations can be approved or rejected"
            )

    def reject(self) -> None:
        self.ensure_can_process_approval()
        self.state = "CANCELLED"

    def is_expired(self, now: datetime) -> bool:
        return now >= self.start_time

    def mark_expired(self) -> None:
        self.state = "CANCELLED"

    def approve(self, has_conflict: bool) -> None:
        self.ensure_can_process_approval()
        if has_conflict:
            raise ReservationConflictError(
                "Conflict: Resource was already confirmed for an overlapping slot"
            )
        self.state = "CONFIRMED"

    def cancel(self, now: datetime) -> bool:
        """
        Transitions to CANCELLED if strictly before start_time (BR-03).
        Returns True if state actually changed, False if idempotent repeat.
        """
        if self.state == "CANCELLED":
            return False
        if now >= self.start_time:
            raise InvalidStateTransitionError(
                "Policy Violation: Cannot cancel after the start time"
            )
        self.state = "CANCELLED"
        return True


class BookingPolicy:
    MAX_DAILY_SECONDS: int = 4 * 3600

    @staticmethod
    def validate_interval(start_time: datetime, end_time: datetime) -> None:
        if start_time >= end_time:
            raise InvalidIntervalError(
                "Invalid interval: start time must be before end time"
            )

    @classmethod
    def validate_daily_quota(
        cls,
        existing_reservations: list[ReservationEntity],
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        total_seconds = sum(
            (r.end_time - r.start_time).total_seconds() for r in existing_reservations
        )
        new_duration = (end_time - start_time).total_seconds()
        if (total_seconds + new_duration) > cls.MAX_DAILY_SECONDS:
            raise DailyQuotaExceededError(
                "Domain Rule Violation: 4-hour daily limit exceeded"
            )

    @staticmethod
    def requires_admin_approval(resource_id: str) -> bool:
        """Rooms prefixed with 'VIP_' require explicit administrator approval."""
        return resource_id.startswith("VIP_")
