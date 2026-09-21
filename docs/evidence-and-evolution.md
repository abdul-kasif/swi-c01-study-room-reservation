# C01 Engineering Spike

**Question / unknown:**
Can a team member reliably initialize the Python FastAPI environment and SQLite database from a clean repository across different operating systems using only the README instructions?

**What we did:**
Abdul committed a `requirements.txt`, an empty SQLite configuration in `main.py`, and a declarative `Taskfile.yml` for build orchestration. Nithik then performed a clean checkout of the repository to build, test, and run the API using only the steps provided in the README.

**Observed result:**
While testing the cross-platform setup between Windows hosts and Abdul's Fedora Linux environment, the build encountered path separation anomalies and binary name discrepancies for the virtual environment execution directory. Additionally, the target and instructions to run the automated tests (`pytest`) were entirely missing from the initial configuration.

**Decision / what changes because of the result:**
We fixed the discovered obstacles by refactoring the `Taskfile.yml` to include OS variable detection logic, mapping the virtual environment directory dynamically (`bin` vs `Scripts`), and shifting to standard Python module executions (`python -m uvicorn`). We also added a dedicated `task test` target and updated the `README.md` to guarantee full, cross-platform reproducibility.