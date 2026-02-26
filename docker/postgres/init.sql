-- PostgreSQL initialization script
-- Schema is managed by SQLAlchemy (auto-create on startup) + Alembic (migrations).
-- This file handles database-level setup only.

-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
