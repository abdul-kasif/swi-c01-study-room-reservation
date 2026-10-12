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
All 10 automated verification tests in `test_main.py` were executed via `task test` (`pytest` + `httpx` TestClient) and passed:

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

