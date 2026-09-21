# Study Room Reservation System

This repository contains a Study Room Reservation System developed for the SWI C01 Software Engineering course. Built using Python 3, FastAPI, and an embedded SQLite database, the API allows students to request room slots and administrators to manage availability.

## Team Information

- **Team Name:** ANS Systems
- **Members:** Abdul Kasif (RAJ0111), Nithik (ANA0013), Subash (SOU0156)
- **Repository URL:** [https://github.com/abdul-kasif/swi-c01-study-room-reservation]

## CP1 Walking Skeleton

The following end-to-end path must be truly runnable after C03 / before C04:

1. `POST /reservations`
2. Validate domain rule (maximum 4 hours per day)
3. Persist to SQLite database
4. Return reservation ID
5. Automated check execution

## Local Setup & Execution

To start the application from a clean repository, run the following commands:

1. `task setup`
2. `task run`
