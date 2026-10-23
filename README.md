# Study Room Reservation System

This repository contains a Study Room Reservation System developed for the SWI C01 Software Engineering course. Built using Python 3, FastAPI, and an embedded SQLite database, the API allows students to request room slots and administrators to manage availability.

## Team Information

- **Team Name:** ANS Systems
- **Members:** Abdul Kasif (RAJ0111), Nithik (ANA0013), Subash (SOU0156)
- **Repository URL:** <https://github.com/abdul-kasif/swi-c01-study-room-reservation>

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Running Without Task](#running-without-task)
4. [Using the API](#using-the-api)
5. [Running the Tests](#running-the-tests)
6. [Project Structure](#project-structure)
7. [Documentation](#documentation)
8. [Troubleshooting](#troubleshooting)
9. [CP1 Walking Skeleton](#cp1-walking-skeleton)

## Prerequisites

| Tool | Version | Notes |
| :-- | :-- | :-- |
| **Python** | **3.10 or newer** | The code uses `int \| None` annotations, which need 3.10+. Check with `python --version` (Windows) or `python3 --version` (Linux/macOS). |
| **Task** (go-task) | any recent 3.x | Runs the project commands. Install: see below. |
| **Git** | any | To clone the repository. |

No database server is needed: SQLite is embedded and the database file (`reservation.db`) is created automatically on first start.

### Installing Task

| OS | Command |
| :-- | :-- |
| Windows | `winget install Task.Task` or `scoop install task` |
| macOS | `brew install go-task` |
| Linux (Fedora) | `sudo dnf install go-task` |
| Anything else | See <https://taskfile.dev/installation> |

> On some Linux distributions the binary is called `go-task` instead of `task`. If `task` is not found, use `go-task` everywhere below.

## Quick Start

From a clean checkout:

```bash
git clone https://github.com/abdul-kasif/swi-c01-study-room-reservation.git
cd swi-c01-study-room-reservation

task setup   # creates ./venv and installs requirements.txt
task run     # starts the API at http://127.0.0.1:8000 (auto-reload on)
task test    # runs the automated tests (pytest)
```

Once `task run` is running:

- API base URL: <http://127.0.0.1:8000>
- Interactive API docs (Swagger UI): <http://127.0.0.1:8000/docs>
- Stop the server with `Ctrl+C`.

`task setup` works on Windows (CMD/PowerShell) and Linux/macOS: the Taskfile detects the OS and uses `venv/Scripts` or `venv/bin` accordingly, and always invokes tools as `python -m ...`.

## Running Without Task

If you cannot install Task, these are the equivalent commands.

**Linux / macOS**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

.venv/bin/python -m uvicorn src.main:app --reload   # run
.venv/bin/python -m pytest                          # test
```

**Windows (CMD / PowerShell)**

```bat
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt

.venv\Scripts\python -m uvicorn src.main:app --reload
.venv\Scripts\python -m pytest
```

Always run these commands from the repository root (the folder containing `Taskfile.yml`), because `src.main:app` and the SQLite path `./reservation.db` are relative to it.

## Using the API

| Operation | Endpoint | Body |
| :-- | :-- | :-- |
| OP-01 Create reservation (`DRAFT`) | `POST /reservations` | `resource_id`, `user_id`, `start_time`, `end_time` |
| OP-02 Check availability | `POST /availability` | `resource_id`, `start_time`, `end_time` |
| OP-03 Confirm reservation | `POST /reservations/{id}/confirm` | none |
| OP-04 Cancel reservation | `POST /reservations/{id}/cancel` | none |
| OP-05 Approve / reject (admin) | `POST /reservations/{id}/approval` | `admin_id`, `decision` (`approve` or `reject`) |

Times are ISO-8601 (for example `2030-01-07T10:00:00`) and are treated as local server time.

### Example session (Linux/macOS/Git Bash)

```bash
# 1. Create a draft (returns {"id": 1, "state": "DRAFT"})
curl -X POST http://127.0.0.1:8000/reservations \
  -H "Content-Type: application/json" \
  -d '{"resource_id":"Room1","user_id":"alice","start_time":"2030-01-07T10:00:00","end_time":"2030-01-07T12:00:00"}'

# 2. Check availability (AVAILABLE until a reservation is CONFIRMED)
curl -X POST http://127.0.0.1:8000/availability \
  -H "Content-Type: application/json" \
  -d '{"resource_id":"Room1","start_time":"2030-01-07T10:00:00","end_time":"2030-01-07T12:00:00"}'

# 3. Confirm it (standard room -> CONFIRMED)
curl -X POST http://127.0.0.1:8000/reservations/1/confirm

# 4. Cancel it (only allowed strictly before start_time)
curl -X POST http://127.0.0.1:8000/reservations/1/cancel
```

**Restricted rooms:** resource IDs starting with `VIP_` need administrator approval. Confirming such a reservation gives `PENDING_APPROVAL`; then:

```bash
curl -X POST http://127.0.0.1:8000/reservations/2/approval \
  -H "Content-Type: application/json" \
  -d '{"admin_id":"admin1","decision":"approve"}'
```

On Windows PowerShell, use the Swagger UI at `/docs` (easiest) or `Invoke-RestMethod`.

### Business rules enforced

| Rule | Meaning |
| :-- | :-- |
| BR-01 | Intervals are half-open `[start, end)`; a booking ending at 10:00 does not conflict with one starting at 10:00. |
| BR-02 | Two `CONFIRMED` reservations for the same room must never overlap. |
| BR-03 | Cancellation is allowed only strictly before the start time; repeating a cancel is harmless. |
| BR-04 | A user may book at most 4 hours per day (counting `DRAFT`, `PENDING_APPROVAL`, `CONFIRMED`). |
| v0.2 | `VIP_` rooms go `DRAFT -> PENDING_APPROVAL -> CONFIRMED/CANCELLED`; approving at or after the start time cancels the reservation. |

### HTTP status codes

| Code | Meaning |
| :-- | :-- |
| 200 | Success |
| 400 | Invalid interval, daily quota exceeded, or illegal state transition (including cancel after start) |
| 404 | Reservation not found |
| 409 | Conflict with an already `CONFIRMED` reservation |
| 422 | Malformed request body (e.g. missing field, unknown `decision`) |

## Running the Tests

```bash
task test
```

Run a single file or test with pytest directly:

```bash
venv/bin/python -m pytest test_main_c02.py -v        # Linux/macOS
venv\Scripts\python -m pytest test_main_c03.py -v    # Windows
```

| File | Purpose |
| :-- | :-- |
| `test_main_c02.py` | Behavioural tests for OP-01 to OP-05 plus the architecture rule check (the API layer must not mutate `.state` or call `.query()` / `.commit()`). |
| `test_main_c03.py` | Hard cases: interval boundaries, daily quota edges, state-transition rules, VIP approval conflicts and expiry, request validation. |
| `test_main_c05.py` | (C05) Tests derived from the detailed design of confirmation/approval handling. Present once the C05 change is merged. |

> **Important:** `test_main_c02.py` and `test_main_c03.py` reset the real `./reservation.db` before every test (`drop_all` / `create_all`). Running `task test` **deletes any data** you created while using `task run`. Do not run the tests against data you want to keep. `test_main_c05.py` uses temporary databases and does not touch `reservation.db`.

## Project Structure

```text
.
├── README.md
├── Taskfile.yml              # setup / run / test commands
├── requirements.txt          # Python dependencies
├── .gitignore
├── test_main_c02.py          # behaviour + architecture-rule tests
├── test_main_c03.py          # hard-case tests
├── docs/
│   ├── intent-and-change.md          # project frame, specification baselines v0.1 / v0.2
│   ├── evidence-and-evolution.md     # verification evidence per milestone
│   └── architecture-and-decisions.md # architecture, ADR-01, detailed design
└── src/
    ├── main.py               # FastAPI routes + error translation (transport layer)
    ├── service.py            # ReservationService: use-case orchestration
    ├── domain.py             # ReservationEntity (state machine), BookingPolicy, domain errors
    ├── repository.py         # SQLAlchemy model + all database queries
    └── notifications.py      # NotificationGateway (external boundary stub)
```

Layering (ADR-01): `main.py` -> `service.py` -> `domain.py` / `repository.py` / `notifications.py`. The HTTP layer never touches the database or mutates reservation state directly.

## Documentation

| Document | Contents |
| :-- | :-- |
| [`docs/intent-and-change.md`](docs/intent-and-change.md) | Project frame, stack rationale, minimum behaviour specification (v0.1) and the approval-workflow change (v0.2) |
| [`docs/evidence-and-evolution.md`](docs/evidence-and-evolution.md) | C01 engineering spike, C02 verification evidence, C05 detailed-design verification |
| [`docs/architecture-and-decisions.md`](docs/architecture-and-decisions.md) | C03 AS-IS/TO-BE architecture, ADR-01, C05 detailed design |

## Troubleshooting

| Problem | Fix |
| :-- | :-- |
| `task: command not found` | Install Task (see above), or on Linux try `go-task`. Or use [Running Without Task](#running-without-task). |
| `python3: command not found` (Linux/macOS) / `python` not found (Windows) | Install Python 3.10+ and make sure it is on your `PATH`. |
| `TypeError: unsupported operand type(s) for \|` or similar syntax errors | Your Python is older than 3.10. Upgrade and re-run `task setup` (delete the `venv` folder first). |
| `ModuleNotFoundError: No module named 'src'` | Run commands from the repository root, not from inside `src/`. |
| `ModuleNotFoundError` for `fastapi`, `sqlalchemy`, etc. | Run `task setup` again, and use the venv's Python (`task run` / `task test` already do). |
| `starlette.testclient requires the httpx2 package` | Install requirements with `task setup`; `httpx2` is listed in `requirements.txt`. |
| Port 8000 already in use | Stop the other process, or run uvicorn on another port: `venv/bin/python -m uvicorn src.main:app --reload --port 8001`. |
| Want a fresh database | Stop the server and delete `reservation.db`; it is re-created on next start. |
| Tests wiped my data | Expected for `test_main_c02.py` / `test_main_c03.py` (see the warning above). |

## CP1 Walking Skeleton

The following end-to-end path must be truly runnable after C03 / before C04:

1. `POST /reservations`
2. Validate domain rule (maximum 4 hours per day)
3. Persist to SQLite database
4. Return reservation ID
5. Automated check execution

It is exercised by `test_op01_create_success` and `test_op01_create_negative_limit_exceeded` in `test_main_c02.py`, and by the manual `curl` example above.
