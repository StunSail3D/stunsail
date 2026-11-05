# ADR 0003: SQLite-first migrations with Alembic

- Status: Accepted for Phase 0
- Date: 2026-11-04

## Context

The first release needs local SQLite persistence, while Core should be able to
support PostgreSQL later. Schema history must be testable from the start.

## Decision

Use SQLAlchemy 2 and Alembic for all Core schema migrations. Every schema change
is a reviewed, immutable revision. Test upgrade and downgrade on disposable
SQLite databases, use batch operations for SQLite table changes, and keep
migration operations portable. Use a pre-upgrade backup and restore plan for
production recovery rather than relying on destructive downgrade behavior.

The Phase 0 baseline migration is intentionally empty because the final schema
is defined with Core domain implementation.

## Consequences

Schema evolution is explicit and reproducible. Generated revisions are not
accepted without review, and portability to PostgreSQL remains a required design
constraint.
