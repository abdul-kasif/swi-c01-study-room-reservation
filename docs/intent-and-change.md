# Project Frame

## Reservation domain

We reserve Study Rooms.

## Purpose

The system provides university students with an equitable platform to reserve local campus study spaces for individual or group work. It exists to eliminate booking conflicts, maximize room utilization, and streamline room management for administrative staff.

## Users / Stakeholders

- **Student**: Creates initial reservation drafts and manages their allocated daily slots.
- **Administrator**: Approves, rejects, and manages the operational status of study rooms.

## Core concepts

- **Resource**: The physical Study Room containing attributes like name, capacity, and location.
- **Reservation**: The booking record tracking the allocated time block, state, and room reference.
- **User**: The identity of the student or administrator executing system commands.

## Core operations

- Create reservation
- Confirm / approve reservation
- Cancel reservation
- Check availability

## Persistent state

- **Resource Data:** ID, room name, capacity limits, and operational availability status flags.
- **Reservation Data:** ID, resource relationship ID, creator user ID, date, start time, end time, and state tracker string.

## State-changing operation

`DRAFT` → `CONFIRMED` (Upon authorization, verification, or administrator approval steps).
`CONFIRMED` → `CANCELLED` (When a user or admin revokes an active slot).

## Common business rule

Two CONFIRMED reservations for the exact same room must not overlap.

## Domain-specific business rule

A single user can book a maximum of 4 total hours per day, which can be divided across multiple custom time slots.

## External / system boundary

Notification Service.

## Assumption

We assume that the Notification Service will always respond within 2 seconds, allowing us to send emails synchronously during the booking process without freezing the API.

## Unknown

We do not yet know how the system should handle orphaned DRAFT reservations if a user abandons the application before hitting "Confirm".

## Selected future pressure

- **Category:** C (Changeability)
- **Concrete pressure:** Expanding the system to support additional bookable resources (e.g., projectors, whiteboards, or laptops) alongside rooms, each with entirely different maximum booking time limits.
- **Why it is relevant to our reservation system:** Study rooms often require physical equipment. If the university administration wants to manage hardware checkout through the same system, our data model and the hardcoded 4-hour daily limit rule will need to be refactored to handle dynamic rules based on the resource type.

---

# Stack Rationale

The team has opted for a Python-based stack because all members possess strong existing proficiency in the language, minimizing the learning curve and maximizing productivity for a time-boxed engineering exercise. FastAPI was selected for its fast execution, native support for asynchronous endpoints, and automatic API documentation. SQLite replaces PostgreSQL because its embedded, zero-configuration nature drastically simplifies local setup, making it trivial to achieve a reproducible build across different environments without managing external database containers.
