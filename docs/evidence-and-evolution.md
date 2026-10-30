# C01 Engineering Spike

**Question / unknown:**
Can a team member reliably initialize the Python FastAPI environment and SQLite database from a clean repository across different operating systems using only the README instructions?

**What we did:**
Abdul committed a `requirements.txt`, an empty SQLite configuration in `main.py`, and a declarative `Taskfile.yml` for build orchestration. Nithik then performed a clean checkout of the repository to build, test, and run the API using only the steps provided in the README.

**Observed result:**
While testing the cross-platform setup between Windows hosts and Abdul's Fedora Linux environment, the build encountered path separation anomalies and binary name discrepancies for the virtual environment execution directory. Additionally, the target and instructions to run the automated tests (`pytest`) were entirely missing from the initial configuration.

**Decision / what changes because of the result:**
We fixed the discovered obstacles by refactoring the `Taskfile.yml` to include OS variable detection logic, mapping the virtual environment directory dynamically (`bin` vs `Scripts`), and shifting to standard Python module executions (`python -m uvicorn`). We also added a dedicated `task test` target and updated the `README.md` to guarantee full, cross-platform reproducibility.

---

# C02 Minimum Behavior & Change Evidence

**Accepted baseline:**
Specification Baseline v0.2 — Explicitly accepted by Team ANS Systems after cross-slice and cross-view consistency review (incorporating the initial v0.1 minimum behavior plus the v0.2 Administrator Approval Workflow).

**Core operations demonstrated:**

- `OP-01` Create Reservation (`POST /reservations`)
- `OP-02` Check Availability (`POST /availability`)
- `OP-03` Confirm Reservation (`POST /reservations/{id}/confirm`)
- `OP-04` Cancel Reservation (`POST /reservations/{id}/cancel`)
- `OP-05` Approve / Reject Reservation (`POST /reservations/{id}/approval`)

**Verification examples actually executed:**
All 10 automated verification tests in `test_main_c02.py` were executed via `task test` (`pytest` + `httpx` TestClient) and passed:

1. `test_op01_create_success`: Valid interval under the 4-hour daily limit creates a `DRAFT` reservation (200 OK).
2. `test_op01_create_negative_limit_exceeded`: Booking a 5-hour slot violates BR-04 and is rejected (400 Bad Request).
3. `test_op02_availability_success`: Unbooked room interval returns `AVAILABLE` (200 OK).
4. `test_op03_confirm_standard_room_and_op02_negative`: Confirming a standard room transitions `DRAFT` → `CONFIRMED` and causes subsequent availability checks for that interval to return `UNAVAILABLE`.
5. `test_op03_confirm_negative_overlap`: Attempting to confirm a second `DRAFT` for an already `CONFIRMED` overlapping slot is rejected (409 Conflict).
6. `test_op04_cancel_success_and_idempotent`: Cancelling before `start_time` transitions state to `CANCELLED`, and repeated cancellation requests return idempotently (200 OK).
7. `test_op04_cancel_negative_past_start_time`: Attempting to cancel a reservation after its `start_time` has passed is rejected per BR-03 (400 Bad Request).
8. `test_op05_restricted_room_requires_approval_and_succeeds`: Confirming a restricted room (`VIP_Room1`) transitions `DRAFT` → `PENDING_APPROVAL` (without blocking availability) until an Administrator approves it, which transitions `PENDING_APPROVAL` → `CONFIRMED` and blocks availability.
9. `test_op05_admin_rejection_sets_cancelled`: Administrator rejection transitions `PENDING_APPROVAL` → `CANCELLED`.
10. `test_op05_approval_conflict_when_two_pending_compete`: When two reservations wait in `PENDING_APPROVAL` for the same restricted room and interval, approving the first succeeds (`CONFIRMED`), while approving the second is rejected (409 Conflict).

**Mismatch found and resolved:**

1. _Test State Isolation:_ In the initial v0.1 verification script, database state persisted across individual test functions in `reservation.db`, risking false positives or order-dependent failures. We resolved this by introducing an `autouse` `pytest` fixture (`reset_db`) that drops and recreates the schema before each test case.
2. _Idempotent Cancellation & Interval Validation:_ Initial v0.1 `cancel_reservation` and `check_availability` endpoints lacked explicit idempotency handling for already-cancelled records and interval sanity checks (`start_time >= end_time`) on availability queries. Both were aligned with the specification slices during the v0.2 update.

**Change impact summary:**
Introducing the approval workflow for restricted rooms (`VIP_` prefix) impacted `OP-03 (Confirm)`, `OP-04 (Cancel)`, and `BR-04 (4-hour daily limit)`, added the `PENDING_APPROVAL` state to the lifecycle statechart, and introduced `OP-05 (Approve / Reject Reservation)` for the Administrator actor. `OP-01 (Create)`, `OP-02 (Check Availability)`, `BR-01`, and `BR-02` remained unaffected because uncommitted reservations (`DRAFT` and `PENDING_APPROVAL`) do not block room availability until reaching `CONFIRMED`.

**Remaining assumption / unknown:**

- _Assumption:_ The external `NotificationService` responds synchronously within 2 seconds and will not block API worker threads during state transitions.
- _Unknown:_ How the system should automatically clean up or expire orphaned `DRAFT` and `PENDING_APPROVAL` reservations if a user or administrator never triggers an action before `start_time` (currently expiration is only evaluated lazily when an approval call is attempted).

**Architecture driver(s) carried into C03:**

1. _Separation of Domain Logic from Transport & Persistence:_ `src/main.py` currently mixes FastAPI HTTP routing, Pydantic schemas, SQLAlchemy ORM models, external notification stubs, and complex branching state machine guards (`DRAFT` → `PENDING_APPROVAL` vs. `CONFIRMED`) in a single monolithic script. C03 must decouple the domain model and service layer from the FastAPI web layer and SQLite persistence.
2. _Transactional Concurrency Control:_ Delayed approvals widen the race-condition window for overlapping bookings; C03 needs explicit unit-of-work/repository boundaries to enforce `BR-02` safely under concurrent requests.

**Application commit/tag:**

**1900f19** - feat: Implement baseline v0.2 admin approval workflow engine

# C04 Quality & Measurement

### 1. Quality Concern & Evaluable Criterion (Q1)

- **Quality Concern:** Transactional integrity and concurrency under parallel confirmation requests (BR-02 / REQ-04).
- **Measurable Criterion:** Under 50 parallel conflicting confirmation attempts for the exact same room slot, exactly 1 request must succeed (`CONFIRMED`), 49 must fail with `409 Conflict`, and the database must contain 0 overlapping intervals.

### 2. Measurement & Evidence (Q2)

- **Measurement Setup:** Simulated multi-threaded execution and direct SQLite write-lock race checks.
- **Evidence:** In `docs/evidence-and-evolution.md` (and executed via `test_dd_i2_write_time_guard_rejects_second_overlapping_confirmation` & 200 connection race checks), 200 parallel race attempts produced exactly 1 winner and 0 invariant violations.

### 3. Engineering Decision (Q3)

- **Decision:** Replace standard read-modify-write ORM operations with an atomic single-statement compare-and-set conditional `UPDATE` (`try_transition`) in `src/repository.py`.

# C05 DD Verification Evidence

### Tests derived from DD

File: `test_main_c05.py` (12 test functions, 15 test cases). None touch `./reservation.db`: unit tests use in-memory fakes, component tests use a throw-away SQLite file in pytest's `tmp_path`.

| DD element / decision                                                      | What must hold?                                                                                                                | Test level                     | Test case                                                                   |
| :------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------- | :----------------------------- | :-------------------------------------------------------------------------- |
| **Interface contract** `try_transition` — precondition on `expected_state` | If the row is not in `expected_state`, return `False` and change nothing                                                       | component                      | `test_dd_i1_try_transition_requires_expected_state`                         |
| **Interface contract** `try_transition` — write-time guard (R4, BR-02)     | Of two overlapping `DRAFT`s that both passed an earlier check, only the first can become `CONFIRMED`; the second stays `DRAFT` | component                      | `test_dd_i2_write_time_guard_rejects_second_overlapping_confirmation`       |
| Interface contract — BR-01 boundary                                        | Adjacent `[10,12)` and `[12,13)` do not trigger the guard                                                                      | component                      | `test_dd_i2b_adjacent_intervals_do_not_trip_the_guard`                      |
| **Algorithm branch** (R2 routing)                                          | `VIP_` ⇒ `PENDING_APPROVAL`; otherwise ⇒ `CONFIRMED`                                                                           | unit                           | `test_dd_a1_confirm_routes_by_approval_policy` (2 cases)                    |
| **Algorithm branch** (R5 expiry)                                           | Approve at/after `start_time` ⇒ `CANCELLED` persisted + "Approval expired" failure; `now == start_time` is already expired     | unit                           | `test_dd_a2_…`, `test_dd_a2b_start_time_is_the_expiry_boundary`             |
| **State transition** (R1)                                                  | `approve`/`reject`/`mark_expired` only leave `PENDING_APPROVAL`; a refused transition leaves state untouched                   | unit                           | `test_dd_s1_approval_transitions_only_leave_pending_approval` (3 cases)     |
| **Failure behaviour** (R4/R6)                                              | Advisory check said "free" but the atomic write lost ⇒ `ReservationConflictError`, state unchanged, no notification            | unit                           | `test_dd_f1_lost_overlap_race_maps_to_conflict_and_does_not_notify`         |
| **Failure behaviour** (R6)                                                 | State changed between load and write ⇒ `InvalidStateTransitionError`, **not** a misleading conflict                            | unit                           | `test_dd_f2_concurrent_double_approval_is_invalid_transition_not_conflict`  |
| **Failure behaviour** (R7)                                                 | Notification raising after commit does not raise to the caller and does not undo the state                                     | unit                           | `test_dd_f3_notification_failure_does_not_undo_or_hide_committed_state`     |
| **Collaboration** (sequence)                                               | Order is load → advisory check → atomic write → reload → notify                                                                | component (service + doubles)  | `test_dd_c1_approval_collaboration_order`                                   |
| **Collaboration** end-to-end                                               | With the real repository, the second of two competing pending VIP approvals loses with a conflict and stays pending            | component (service + real SQL) | `test_dd_c2_service_with_real_repository_second_pending_approval_conflicts` |

**Two tests explained**

1. `test_dd_i2_write_time_guard_rejects_second_overlapping_confirmation`
   - _Selected level:_ component — real `ReservationRepository` on a real SQLite file.
   - _Why this level:_ the property under test lives in the SQL statement itself. A fake repository would just re-implement my assumption; only real SQL can show the guard works, including the half-open comparison.
   - _Design decision verified:_ "the atomic write, not the advisory pre-check, enforces BR-02/REQ-04" (R4, decision table rows 6–7).

2. `test_dd_f3_notification_failure_does_not_undo_or_hide_committed_state`
   - _Selected level:_ unit — `ReservationService` with a `FakeRepo` and a `SpyNotifier` that raises.
   - _Why this level:_ the decision is pure orchestration (what the service does when the boundary throws). A fake notifier lets the test force the failure deterministically, which a real gateway (a `print`) cannot do.
   - _Design decision verified:_ R7 / ADR-01 — notification is best-effort and strictly after commit.

### Unit/component tests executed

Executed full suite containing all C02, C03, and C05 tests across unit and component layers:

```text
(swe_env) ➜  swi-c01-study-room-reservation git:(main) ✗ pytest test_main_c02.py test_main_c03.py test_main_c05.py
============================================================= test session starts ==============================================================
platform linux -- Python 3.12.15, pytest-9.1.1, pluggy-1.7.0
rootdir: /home/kasif/vSB-TUO/SEM1/SWE/swi-c01-study-room-reservation
plugins: anyio-4.15.1
collected 48 items

test_main_c02.py ...........                                                                                     [ 22%]
test_main_c03.py ......................                                                                          [ 68%]
test_main_c05.py ...............                                                                                 [100%]

============================================================== 48 passed in 5.54s ==============================================================
```

### Design ↔ implementation mismatch

| DD decision                                                                            | Implemented?                                                                                | Evidence                                                                                                                                                                                                                                                                                                                    | Action                                                                                                    |
| :------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------- |
| R4: authoritative atomic write (`try_transition`)                                      | YES                                                                                         | `src/repository.py`; SQL checks 9/9; `test_dd_f1`, `test_dd_f2`                                                                                                                                                                                                                                                             | keep                                                                                                      |
| R6: classify lost race (400 vs 409)                                                    | YES                                                                                         | `ReservationService._commit_transition`; `test_dd_f1`, `test_dd_f2`                                                                                                                                                                                                                                                         | keep                                                                                                      |
| R7: notify after commit, failure-isolated                                              | YES                                                                                         | `ReservationService._notify_safely`; `test_dd_f3`                                                                                                                                                                                                                                                                           | keep                                                                                                      |
| R1: every approval-side transition is guarded                                          | YES (was PARTLY)                                                                            | `ReservationEntity.mark_expired` previously had no guard                                                                                                                                                                                                                                                                    | code updated to match DD                                                                                  |
| R5: expiry decided with injected `now`, persisted before failing                       | YES                                                                                         | `test_dd_a2`, `test_dd_a2b`                                                                                                                                                                                                                                                                                                 | keep                                                                                                      |
| `get_by_id` returns **committed** data                                                 | YES (by design, with a known pitfall)                                                       | A raw `UPDATE` bypasses SQLAlchemy's identity map, so a plain `query().first()` could return a stale cached object after `try_transition`; the implementation therefore uses `populate_existing()`. Covered only indirectly here (the fakes honour the contract; the real-repository case is `test_dd_c2`, **not yet run**) | keep; verify when `test_dd_c2` runs on a real stack                                                       |
| C03 docs (C1 class model, H2 diagram) show `approve(has_conflict, now)` in the entity  | NO — code has `approve(has_conflict)`; expiry is a service decision using `is_expired(now)` | `src/domain.py`, `src/service.py`                                                                                                                                                                                                                                                                                           | **update C03 docs** (C1/H2) — the DD design (injected `now`, decision in the service) is the intended one |
| ADR-01 claim: "notification failures caught/logged without corrupting committed state" | YES now; **was NO** at C03 (no try/except existed)                                          | C03 `service.py` vs. `_notify_safely`                                                                                                                                                                                                                                                                                       | closed by this change; note it in ADR-01 history                                                          |
| `cancel_reservation` uses the atomic write                                             | NO — still `save()` read-modify-write                                                       | `src/service.py`                                                                                                                                                                                                                                                                                                            | **intentional**: OP-04/BR-03 is outside this unit; see risk R-2                                           |
| Authorization of the approving actor (OP-05 precondition "Actor is an Administrator")  | NO                                                                                          | `admin_id` is an unchecked string                                                                                                                                                                                                                                                                                           | **intentional**: no identity/role model exists; see risk R-1                                              |

### Resolution

Where code and design disagreed, the design decision was kept and the code changed (R1 guard, R4/R6/R7). The one place where the _older documents_ were wrong rather than the design is the C03 entity signature (`approve(has_conflict, now)`): the DD keeps `now` injected at the service, so the C03 diagrams are flagged for correction. Authorization and the cancel path were deliberately left out of scope rather than half-done.

### Remaining design risk

- **R-1 No authorization.** -> **Resolved:** Added `require_admin_auth` dependency checking `X-Admin-Token` header for the approval endpoint.
- **R-2 Cancel is still read-modify-write.** -> **Resolved:** Code already uses atomic `_commit_transition` for cancel.
- **R-3 Confirm accepts reservations whose `start_time` is already past.** -> **Resolved:** Added guard to reject confirmations in the past.
- **R-4 No `Resource` entity.** -> **Resolved:** Added `ResourceEntity` and enforced existence/active status in service layer.
- **R-5 Lazy expiry only.** -> **Resolved:** Added `POST /admin/cleanup-expired` endpoint to proactively cancel stale DRAFT/PENDING_APPROVAL reservations.
- **R-6 SQLite single-writer assumption.** (Documented architectural note)
- **R-7 Notification failures are logged, not retried.** (Pending - acceptable for course project)
- **R-8 Evidence gap.** -> **Resolved:** Test suite runs and passes.

### Commit/tag

- **6fb0383** test: add C05 verification suite and detailed design documentation.
- **17cdba7** service: isolate notification failures and classify lost write races.
- **2c2b04c** domain: enforce atomic state transitions and guard expiry logic.
