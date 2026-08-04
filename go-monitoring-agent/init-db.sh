#!/bin/bash

# TimescaleDB Database Initialization Script
# This script creates tables, runs migrations, and sets up compression/retention policies

set -e  # Exit on error

# Configuration - these can be overridden via environment variables
PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"
PG_DATABASE="${PG_DATABASE:-go_monitoring_agent}"
PG_PASSWORD="${PG_PASSWORD:-postgres}"

MIGRATIONS_DIR="schema/migrations"
SCHEMA_VERSION_FILE=".timescaledb_schema_version"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

error() {
    echo "ERROR: [$1]" >&2
    exit 1
}

# Build PGPASSWORD environment variable if password is set
export PGPASSWORD="$PG_PASSWORD"

log "Connecting to PostgreSQL at $PG_HOST:$PG_PORT..."

# Test connection to PostgreSQL
if ! psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d postgres -c "\q" 2>/dev/null; then
    error "Cannot connect to PostgreSQL server. Check connection parameters."
fi

# Create database if it doesn't exist
log "Checking if database '$PG_DATABASE' exists..."
if ! psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '$PG_DATABASE'" | grep -q 1; then
    log "Creating database '$PG_DATABASE'..."
    createdb -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" "$PG_DATABASE" || error "Failed to create database"
else
    log "Database '$PG_DATABASE' already exists."
fi

# Connect to the database and set up schema
log "Setting up TimescaleDB schema in '$PG_DATABASE'..."

psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DATABASE" <<EOF
-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Set search path to include extensions
SET search_path TO public, timescaledb;

EOF

# Run migration files in order
log "Running SQL migrations..."
for migration in "$MIGRATIONS_DIR"/0*.sql; do
    if [ -f "$migration" ]; then
        log "Applying $(basename "$migration")..."
        if ! psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DATABASE" -f "$migration"; then
            error "Failed to apply migration: $(basename "$migration")"
        fi
        # Track applied migrations
        echo "$(basename "$migration")" >> "$SCHEMA_VERSION_FILE"
    fi
done

# Verify critical components
log "Verifying schema setup..."

psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DATABASE" <<EOF
-- Verify hypertables were created
SELECT hypertable_name, table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN ('host_metrics', 'docker_metrics')
ORDER BY table_name;

-- Verify continuous aggregates exist
SELECT matviewname FROM pg_matviews 
WHERE schemaname = 'public' 
AND matviewname LIKE '%_aggregate%' 
OR matviewname LIKE '%_metrics_%';

-- Verify retention policies
SELECT policy_name, schedule_interval, constraint_value 
FROM _timescaledb_internal.policies 
WHERE policy_type = 'retention';

-- Verify compression policies
SELECT policy_name, schedule_interval, compress_chunk_interval 
FROM _timescaledb_internal.policies 
WHERE policy_type = 'compression';

EOF

log "Schema setup completed successfully!"
log "Tables created:"
log "  - host_metrics (hypertable with compression & retention)"
log "  - docker_metrics (hypertable with compression & retention)"
log "  - subagent_metrics (standard table)"
log ""
log "Continuous Aggregates:"
log "  - host_metrics_1m, host_metrics_5m, host_metrics_1h"
log "  - docker_metrics_1m, docker_metrics_5m, docker_metrics_1h"
log ""
log "Policies:"
log "  - Compression: 7 days -> 1 hour chunks"
log "  - Retention: Remove data older than 90 days"
log "  - Subagent Metrics: Remove after 30 days"
