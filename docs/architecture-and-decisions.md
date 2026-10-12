# C03 — Architecture and Decisions

## Part A: AS-IS Realization of One Scenario

### A1. Identify the Scenario

| Item                     | Value                                                                                                                            |
| :----------------------- | :------------------------------------------------------------------------------------------------------------------------------- |
| **Scenario / Operation** | `OP-03 — Confirm Reservation`                                                                                                    |
| **Requirements**         | `REQ-03` (Confirm DRAFT when resource active and no overlap), `REQ-04` (Concurrent conflict protection), `v0.2 Approval Routing` |
| **Rules / Invariants**   | `BR-01` (Interval semantics `[start, end)`), `BR-02` (Exclusive Resource invariant)                                              |
| **Baseline**             | `v0.2`                                                                                                                           |

---

### A2. Map the Main Scenario Path to Code

Tracing the `OP-03 — Confirm Reservation` main success path against `src/main.py` and `test_main.py`:

| C02 Scenario Step                                   | Implementation Location                                                                  | Evidence                                                                                                                             |
| :-------------------------------------------------- | :--------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------- |
| **1. Accept confirmation request**                  | `src/main.py` → `confirm_reservation(reservation_id: int, db: Session)`                  | FastAPI route `@app.post("/reservations/{reservation_id}/confirm")`; verified by `test_op03_confirm_standard_room_and_op02_negative` |
| **2. Load Reservation**                             | `src/main.py` → `db.query(Reservation).filter(Reservation.id == reservation_id).first()` | Inline SQLAlchemy query inside `confirm_reservation()`; raises `404` if `None`                                                       |
| **3. Check transition is allowed**                  | `src/main.py` → `if res.state != "DRAFT":`                                               | Inline guard inside `confirm_reservation()`; raises `HTTPException(400)` if state is not `DRAFT`                                     |
| **4. Evaluate conflict (BR-02)**                    | `src/main.py` → `db.query(Reservation).filter(...)`                                      | Inline SQLAlchemy query checking `state == "CONFIRMED"`, `start_time < res.end_time`, and `end_time > res.start_time`                |
| **5. Evaluate approval requirement & change state** | `src/main.py` → `requires_approval(res.resource_id)` and `res.state = ...`               | Mutates `res.state = "PENDING_APPROVAL"` if `resource_id.startswith("VIP_")`, otherwise mutates `res.state = "CONFIRMED"`            |
| **6. Persist result**                               | `src/main.py` → `db.commit()`                                                            | Direct SQLAlchemy `Session.commit()` call inside the endpoint handler                                                                |
| **7. Trigger notification**                         | `src/main.py` → `NotificationService.notify(res.user_id, ...)`                           | Synchronous static method call following `db.commit()`                                                                               |

---

### A3. Map One Important Alternative / Failure Path

**Selected Branch:** Overlapping `CONFIRMED` reservation exists (`BR-02` violation) → confirmation is rejected.

| Aspect                          | Details                                                                                                                                                                        |
| :------------------------------ | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **v0.2 Behaviour**              | Overlapping `CONFIRMED` reservation exists → reject confirmation; reservation remains in `DRAFT` state and caller receives `409 Conflict`.                                     |
| **Where condition is detected** | `src/main.py` → inside `confirm_reservation()` via the inline SQLAlchemy query `overlap = db.query(Reservation).filter(...).first()`.                                          |
| **Where outcome is decided**    | `src/main.py` → directly inside the HTTP route handler (`if overlap: raise HTTPException(status_code=409, ...)`).                                                              |
| **What caller receives**        | HTTP `409 Conflict` with JSON body `{"detail": "Conflict: Resource was already booked by another user"}` (verified by `test_op03_confirm_negative_overlap` in `test_main.py`). |

**Specification ↔ Implementation Mismatch Record:**

| Specification (v0.2)                                                                                                                                                        | Current Implementation (`src/main.py`)                                                                                                                                                                                                                                     | Evidence                                                                                                                                                |
| :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `REQ-03` specifies confirming a `DRAFT` only when the Resource is active and exists, and `REQ-04` requires protection against concurrent conflicting confirmation attempts. | 1. No separate `Resource` table/entity exists yet (`resource_id` is an unvalidated string).<br>2. Conflict detection (`SELECT`) and state mutation (`UPDATE`/`COMMIT`) execute as separate non-locking statements without transaction isolation against parallel requests. | `src/main.py`: `Reservation` model only stores `resource_id = Column(String)`. `confirm_reservation()` runs `.first()` followed later by `db.commit()`. |

---

### A4. Select the Main Implementation Elements

Because the C02 baseline was generated as a single-file script (`src/main.py`), all elements currently reside in one module at the function/class level:

| Implementation Element        | Type / Contents                                                         | Role in this Scenario                                                                                                                               | Evidence                          |
| :---------------------------- | :---------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------- |
| **Confirm Endpoint Handler**  | Function: `confirm_reservation()` (`src/main.py`)                       | Accepts HTTP `POST`, orchestrates loading, validates `DRAFT` state and `BR-02` conflicts, mutates state, commits to DB, and triggers notification.  | `src/main.py` (lines 95–128)      |
| **Approval Policy Helper**    | Function: `requires_approval()` (`src/main.py`)                         | Evaluates domain policy (`resource_id.startswith("VIP_")`) to decide between `CONFIRMED` and `PENDING_APPROVAL` target states.                      | `src/main.py` (lines 48–50)       |
| **Reservation ORM Model**     | Class: `Reservation(Base)` (`src/main.py`)                              | Holds in-memory reservation fields (`id`, `resource_id`, `user_id`, `start_time`, `end_time`, `state`) and maps to the `reservations` SQLite table. | `src/main.py` (lines 12–20)       |
| **Database Session Provider** | Function & Engine: `get_db()`, `SessionLocal`, `engine` (`src/main.py`) | Manages the SQLAlchemy `Session` lifecycle connected to `sqlite:///./reservation.db`.                                                               | `src/main.py` (lines 8–10, 26–31) |
| **Notification Service Stub** | Class: `NotificationService` (`src/main.py`)                            | Simulates the external boundary by synchronously printing confirmation/pending alerts for the user.                                                 | `src/main.py` (lines 34–38)       |

---

### A5. Identify State, State Change, and One Rule

#### 1. State

| Question                                                             | Answer                                                                                                                                                                                               | Evidence                                                                                                                                |
| :------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------- |
| **Where is Reservation state persisted?**                            | In the `state` column (`VARCHAR`/`String`) of the `reservations` table inside the local SQLite database file (`./reservation.db`).                                                                   | `src/main.py`: `class Reservation(Base)` defines `state = Column(String)` and `SQLALCHEMY_DATABASE_URL = "sqlite:///./reservation.db"`. |
| **Which code decides/executes the transition used in the scenario?** | The FastAPI endpoint function `confirm_reservation()` directly evaluates the guards (`res.state != "DRAFT"`, `overlap`, `requires_approval()`) and mutates `res.state` before calling `db.commit()`. | `src/main.py`: `res.state = "PENDING_APPROVAL"` or `res.state = "CONFIRMED"` inside `confirm_reservation()`.                            |

#### 2. Business Rule / Invariant (`BR-02`: Exclusive Resource Invariant)

| Question                                           | Answer                                                                                                                                                               | Evidence                                                                                                                                                                                                 |
| :------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Where is the rule condition detected?**          | Duplicated in three places inside `src/main.py`:<br>1. `confirm_reservation()`<br>2. `approve_or_reject_reservation()`<br>3. `check_availability()`                  | All three route handlers execute raw `db.query(Reservation).filter(Reservation.resource_id == ..., Reservation.state == "CONFIRMED", Reservation.start_time < ..., Reservation.end_time > ...).first()`. |
| **Where is the outcome decided?**                  | Directly inside the HTTP route handlers (`confirm_reservation()` and `approve_or_reject_reservation()`) via `if overlap: raise HTTPException(status_code=409, ...)`. | `src/main.py` inside `@app.post("/reservations/{reservation_id}/confirm")` and `@app.post("/reservations/{reservation_id}/approval")`.                                                                   |
| **Where is the resulting state change performed?** | Directly inside `confirm_reservation()` (and `approve_or_reject_reservation()`) via attribute assignment `res.state = "CONFIRMED"` followed by `db.commit()`.        | `src/main.py` inside both route functions.                                                                                                                                                               |

---

### A6. Record Relevant Dependencies

| Dependency                             | Where it connects to your code                                                                                        | Which part knows its technical API                                                                                                                | Evidence                                                                             |
| :------------------------------------- | :-------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------ | :----------------------------------------------------------------------------------- |
| **SQLite Database (`reservation.db`)** | Connected via SQLAlchemy `engine` and `Session` injected into `confirm_reservation(db: Session = Depends(get_db))`.   | The FastAPI route handlers (`confirm_reservation`, etc.) directly invoke SQLAlchemy ORM query methods (`db.query()`, `.filter()`, `db.commit()`). | `src/main.py`: `Session` is imported and queried directly in every endpoint handler. |
| **Notification Service**               | Called directly at the end of `confirm_reservation()`, `approve_or_reject_reservation()`, and `cancel_reservation()`. | The FastAPI route handlers directly call `NotificationService.notify(user_id, message)`.                                                          | `src/main.py`: `NotificationService.notify(...)` invoked inline after `db.commit()`. |

---

### A7. AS-IS Structural Diagram

```text
+-------------------------- Application code (src/main.py) --------------------------+
|                                                                                    |
|  [Confirm Endpoint Handler] (function: confirm_reservation)                        |
|  role: accepts HTTP POST, checks DRAFT state & BR-02 overlap, mutates state        |
|       |                        |                              |                    |
|       | requires_approval()    | query/mutate Reservation     | notify(user, msg)  |
|       v                        v                              v                    |
|  [Approval Policy Helper]  [Reservation ORM Model]     [Notification Stub]         |
|  (func: requires_approval) (class: Reservation)        (class: NotificationService)|
|  role: checks "VIP_" rule  role: maps table columns    role: formats/sends alert   |
|                                |                              |                    |
|                                | Session query / commit       |                    |
|                                v                              |                    |
|                        [DB Session Provider]                  |                    |
|                        (func: get_db / SessionLocal)          |                    |
|                        role: manages SQLAlchemy session       |                    |
+--------------------------------|------------------------------|--------------------+
                                 | SQL read/write               | stdout / sync call
                                 v                              v
                        [SQLite Database]            [External Notification Boundary]
                        (reservation.db)               (Simulated Console Output)
```

**Contained Code Elements (all currently inside `src/main.py`):**

- Confirm Endpoint Handler: `confirm_reservation()`
- Approval Policy Helper: `requires_approval()`
- Reservation ORM Model: `Reservation(Base)`
- DB Session Provider: `get_db(), SessionLocal, engine`
- Notification Stub: `NotificationService`

---

### A8. Architecture Question for C03 Design

| Item               | Content                                                                                                                                                                                                                                                                        |
| :----------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Question**       | How should we decouple reservation state-transition rules (`DRAFT` → `PENDING_APPROVAL` / `CONFIRMED`) and the duplicated `BR-02` overlap check from the FastAPI HTTP handlers and SQLAlchemy `Session` calls so that domain invariants are enforced in one testable boundary? |
| **Evidence**       | In `src/main.py`, the exact SQLAlchemy overlap query (`BR-02`) is copy-pasted across `check_availability()`, `confirm_reservation()`, and `approve_or_reject_reservation()`, and HTTP handlers directly mutate `res.state` and call `db.commit()`.                             |
| **Why it matters** | Any change to interval overlap rules, resource types (our C01 selected future pressure), or transaction locking (`REQ-04`) currently requires modifying multiple FastAPI route functions simultaneously, risking inconsistent state transitions and violating `BR-02`.         |

---
