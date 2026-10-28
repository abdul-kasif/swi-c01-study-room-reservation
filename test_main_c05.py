"""
C05 — tests derived from the Detailed Design of the
"Reservation confirmation & approval handling" unit.

Each test name carries the DD element it verifies (DD-xx, see
docs/architecture-and-decisions.md, section "C05 Detailed Design").

These tests never touch ./reservation.db:
  * unit tests use in-memory fakes (FakeRepo / SpyNotifier);
  * component tests use a throw-away SQLite file under pytest's tmp_path.
"""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.domain import (
    InvalidStateTransitionError,
    ReservationConflictError,
    ReservationEntity,
)
from src.repository import Base, ReservationRepository
from src.service import ReservationService

START = datetime(2030, 1, 7, 10, 0)
END = START + timedelta(hours=2)
BEFORE_START = START - timedelta(hours=1)
AFTER_START = START + timedelta(minutes=5)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class FakeRepo:
    """In-memory stand-in honouring the ReservationRepository contract."""

    def __init__(self, entities, log=None):
        self.store = {e.id: e for e in entities}
        self.log = log if log is not None else []
        self.advisory_overlap = False  # what has_confirmed_overlap reports
        self.write_conflict = False  # what the atomic write-time guard decides
        self.before_cas = None  # hook: simulate another writer winning a race

    def get_by_id(self, rid):
        self.log.append("get_by_id")
        e = self.store.get(rid)
        return replace(e) if e else None

    def has_confirmed_overlap(self, *args, **kwargs):
        self.log.append("has_confirmed_overlap")
        return self.advisory_overlap

    def try_transition(self, rid, expected_state, new_state, enforce_no_overlap):
        self.log.append("try_transition")
        if self.before_cas:
            self.before_cas(self.store[rid])
        e = self.store[rid]
        if e.state != expected_state:
            return False
        if enforce_no_overlap and self.write_conflict:
            return False
        e.state = new_state
        return True

    def save(self, entity):
        self.store[entity.id] = replace(entity)
        return replace(entity)


class SpyNotifier:
    def __init__(self, log=None, fail=False):
        self.calls = []
        self.log = log if log is not None else []
        self.fail = fail

    def notify_state_change(self, *args, **kwargs):
        self.log.append("notify")
        self.calls.append((args, kwargs))
        if self.fail:
            raise RuntimeError("notification service down")


def make_entity(rid=1, resource="Room-A", state="DRAFT", start=START, end=END):
    return ReservationEntity(
        id=rid,
        resource_id=resource,
        user_id="User-A",
        start_time=start,
        end_time=end,
        state=state,
    )


def make_service(entities, fail_notify=False):
    log = []
    repo = FakeRepo(entities, log)
    notifier = SpyNotifier(log, fail=fail_notify)
    return ReservationService(repo=repo, notifier=notifier), repo, notifier, log


@pytest.fixture
def sqlite_repo(tmp_path):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'dd_component.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=eng)
    session = sessionmaker(bind=eng)()

    from src.repository import ResourceModel

    session.add_all(
        [
            ResourceModel(resource_id="Room-A", name="Room A", is_active=True),
            ResourceModel(resource_id="Room-B", name="Room B", is_active=True),
            ResourceModel(resource_id="VIP_R", name="VIP Room R", is_active=True),
            ResourceModel(resource_id="VIP_Room1", name="VIP Room 1", is_active=True),
        ]
    )
    session.commit()

    yield ReservationRepository(session)
    session.close()
    eng.dispose()


def seed(repo, resource="Room-A", state="DRAFT", start=START, end=END, user="U"):
    created = repo.create(
        ReservationEntity(None, resource, user, start, end, state="DRAFT")
    )
    if state != "DRAFT":
        assert repo.try_transition(created.id, "DRAFT", state, False)
    return created.id


# ---------------------------------------------------------------------------
# T1  DD-I1  interface contract: try_transition precondition (expected_state)
#     Level: component (real SQL)
# ---------------------------------------------------------------------------
def test_dd_i1_try_transition_requires_expected_state(sqlite_repo):
    rid = seed(sqlite_repo, state="CONFIRMED")

    applied = sqlite_repo.try_transition(rid, "DRAFT", "CANCELLED", False)

    assert applied is False
    assert sqlite_repo.get_by_id(rid).state == "CONFIRMED"  # unchanged


# ---------------------------------------------------------------------------
# T2  DD-I2  interface contract / BR-02: write-time guard beats a stale
#     advisory check. Level: component (real SQL)
# ---------------------------------------------------------------------------
def test_dd_i2_write_time_guard_rejects_second_overlapping_confirmation(sqlite_repo):
    first = seed(sqlite_repo, user="A")
    second = seed(sqlite_repo, user="B")  # same room, same interval

    # Both callers passed their advisory check earlier (nothing was CONFIRMED).
    assert sqlite_repo.try_transition(first, "DRAFT", "CONFIRMED", True) is True
    assert sqlite_repo.try_transition(second, "DRAFT", "CONFIRMED", True) is False

    assert sqlite_repo.get_by_id(first).state == "CONFIRMED"
    assert sqlite_repo.get_by_id(second).state == "DRAFT"


def test_dd_i2b_adjacent_intervals_do_not_trip_the_guard(sqlite_repo):
    first = seed(sqlite_repo, start=START, end=END)
    second = seed(sqlite_repo, start=END, end=END + timedelta(hours=1))

    assert sqlite_repo.try_transition(first, "DRAFT", "CONFIRMED", True) is True
    assert sqlite_repo.try_transition(second, "DRAFT", "CONFIRMED", True) is True


# ---------------------------------------------------------------------------
# T3  DD-A1  algorithm branch: approval routing (VIP_ -> PENDING, else CONFIRMED)
#     Level: unit
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "resource,expected",
    [("VIP_Room1", "PENDING_APPROVAL"), ("Room1", "CONFIRMED")],
)
def test_dd_a1_confirm_routes_by_approval_policy(resource, expected):
    svc, repo, _, _ = make_service([make_entity(resource=resource)])

    saved = svc.confirm_reservation(1)

    assert saved.state == expected
    assert repo.store[1].state == expected


# ---------------------------------------------------------------------------
# T4  DD-S1  state transition guard: approval only from PENDING_APPROVAL
#     Level: unit
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("state", ["DRAFT", "CONFIRMED", "CANCELLED"])
def test_dd_s1_approval_transitions_only_leave_pending_approval(state):
    e = make_entity(state=state)
    with pytest.raises(InvalidStateTransitionError):
        e.approve(has_conflict=False)
    with pytest.raises(InvalidStateTransitionError):
        e.reject()
    with pytest.raises(InvalidStateTransitionError):
        e.mark_expired()
    assert e.state == state  # failed transition leaves state untouched


# ---------------------------------------------------------------------------
# T5  DD-F1  failure behaviour: advisory said "free" but atomic write lost
#     -> ReservationConflictError, state unchanged, no notification
#     Level: unit
# ---------------------------------------------------------------------------
def test_dd_f1_lost_overlap_race_maps_to_conflict_and_does_not_notify():
    svc, repo, notifier, _ = make_service([make_entity()])
    repo.advisory_overlap = False  # stale: looked free
    repo.write_conflict = True  # but someone confirmed in between

    with pytest.raises(ReservationConflictError):
        svc.confirm_reservation(1)

    assert repo.store[1].state == "DRAFT"
    assert notifier.calls == []


# ---------------------------------------------------------------------------
# T6  DD-F2  failure behaviour: state changed under us -> invalid transition
#     (not a misleading 409). Level: unit
# ---------------------------------------------------------------------------
def test_dd_f2_concurrent_double_approval_is_invalid_transition_not_conflict():
    svc, repo, notifier, _ = make_service(
        [make_entity(resource="VIP_R", state="PENDING_APPROVAL")]
    )
    repo.before_cas = lambda e: setattr(e, "state", "CONFIRMED")  # rival won

    with pytest.raises(InvalidStateTransitionError):
        svc.process_approval(1, "Admin1", "approve", now=BEFORE_START)

    assert notifier.calls == []


# ---------------------------------------------------------------------------
# T7  DD-F3  failure behaviour: notification failure after commit is isolated
#     Level: unit
# ---------------------------------------------------------------------------
def test_dd_f3_notification_failure_does_not_undo_or_hide_committed_state():
    svc, repo, notifier, _ = make_service([make_entity()], fail_notify=True)

    saved = svc.confirm_reservation(1)  # must not raise

    assert saved.state == "CONFIRMED"
    assert repo.store[1].state == "CONFIRMED"
    assert len(notifier.calls) == 1  # it was attempted


# ---------------------------------------------------------------------------
# T8  DD-A2  algorithm branch: expiry. Approving at/after start_time cancels,
#     persists CANCELLED and reports failure. Level: unit
# ---------------------------------------------------------------------------
def test_dd_a2_approval_at_or_after_start_expires_and_cancels():
    svc, repo, notifier, _ = make_service(
        [make_entity(resource="VIP_R", state="PENDING_APPROVAL")]
    )

    with pytest.raises(InvalidStateTransitionError) as exc:
        svc.process_approval(1, "Admin1", "approve", now=AFTER_START)

    assert "Approval expired" in str(exc.value)
    assert repo.store[1].state == "CANCELLED"


def test_dd_a2b_start_time_is_the_expiry_boundary():
    svc, repo, _, _ = make_service(
        [make_entity(resource="VIP_R", state="PENDING_APPROVAL")]
    )

    with pytest.raises(InvalidStateTransitionError):
        svc.process_approval(1, "Admin1", "approve", now=START)  # now == start

    assert repo.store[1].state == "CANCELLED"


# ---------------------------------------------------------------------------
# T9  DD-C1  collaboration: fixed order load -> advisory check -> atomic
#     write -> reload -> notify. Level: component (service + doubles)
# ---------------------------------------------------------------------------
def test_dd_c1_approval_collaboration_order():
    svc, _, _, log = make_service(
        [make_entity(resource="VIP_R", state="PENDING_APPROVAL")]
    )

    svc.process_approval(1, "Admin1", "approve", now=BEFORE_START)

    assert log == [
        "get_by_id",
        "has_confirmed_overlap",
        "try_transition",
        "get_by_id",
        "notify",
    ]


# ---------------------------------------------------------------------------
# T10 DD-C2  collaboration end-to-end on real SQL: the second of two competing
#     pending VIP approvals loses with a conflict. Level: component
# ---------------------------------------------------------------------------
def test_dd_c2_service_with_real_repository_second_pending_approval_conflicts(
    sqlite_repo,
):
    a = seed(sqlite_repo, resource="VIP_R", state="PENDING_APPROVAL", user="A")
    b = seed(sqlite_repo, resource="VIP_R", state="PENDING_APPROVAL", user="B")
    svc = ReservationService(repo=sqlite_repo, notifier=SpyNotifier())

    assert (
        svc.process_approval(a, "Admin1", "approve", BEFORE_START).state == "CONFIRMED"
    )
    with pytest.raises(ReservationConflictError):
        svc.process_approval(b, "Admin1", "approve", BEFORE_START)

    assert sqlite_repo.get_by_id(b).state == "PENDING_APPROVAL"

