#!/bin/bash

set -e

echo "Database Schema Migration Tool"

DB_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/monitoring?sslmode=disable}"

case "$1" in
    create)
        echo "Creating new migration file..."
        NAME=$2
        if [ -z "$NAME" ]; then
            echo "Error: Please provide migration name"
            exit 1
        fi
        TIMESTAMP=$(date +%Y%m%d%H%M%S)
        mkdir -p pkg/database/migrations
        touch "pkg/database/migrations/${TIMESTAMP}_${NAME}.sql"
        echo "Created migration: pkg/database/migrations/${TIMESTAMP}_${NAME}.sql"
        ;;
    
    up)
        echo "Applying migrations..."
        echo "Connecting to: ${DB_URL}"
        psql "${DB_URL}" -c "CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR PRIMARY KEY);"
        find pkg/database/migrations -name "*.sql" -exec basename {} \; | sed 's/_.*//g' | sort -u | while read MIGRATION; do
            MIGRATION_FILE=$(ls pkg/database/migrations/*_${MIGRATION}_*.sql 2>/dev/null | head -n1)
            if [ -n "$MIGRATION_FILE" ] && [ -f "$MIGRATION_FILE" ]; then
                CURRENT_VERSION=$(psql "${DB_URL}" -t -c "SELECT version FROM schema_migrations;" | tr -d ' ')
                if [ "$CURRENT_VERSION" != "$MIGRATION" ]; then
                    echo "Applying migration: ${MIGRATION_FILE}"
                    psql "${DB_URL}" -f "$MIGRATION_FILE"
                    psql "${DB_URL}" -c "INSERT OR IGNORE INTO schema_migrations (version) VALUES ('${MIGRATION}');"
                else
                    echo "Migration already applied: ${MIGRATION}"
                fi
            fi
        done
        echo "All migrations applied!"
        ;;
    
    down)
        echo "Rolling back last migration..."
        LAST_MIGRATION=$(psql "${DB_URL}" -t -c "SELECT MAX(version) FROM schema_migrations;" | tr -d ' ')
        if [ -n "$LAST_MIGRATION" ]; then
            MIGRATION_FILE=$(ls pkg/database/migrations/*_${LAST_MIGRATION}_*.sql 2>/dev/null | head -n1)
            if [ -n "$MIGRATION_FILE" ]; then
                echo "Found rollback file: ${MIGRATION_FILE}"
                psql "${DB_URL}" -f "${MIGRATION_FILE}"
                psql "${DB_URL}" -c "DELETE FROM schema_migrations WHERE version='${LAST_MIGRATION}';"
            fi
        else
            echo "No migrations to roll back"
        fi
        ;;
    
    status)
        echo "Migration status:"
        echo "================================="
        psql "${DB_URL}" -c "SELECT * FROM schema_migrations ORDER BY version DESC;"
        ;;
    
    *)
        echo "Usage: $0 {create|up|down|status}"
        echo ""
        echo "Commands:"
        echo "  create <name>   - Create new migration file"
        echo "  up              - Apply all pending migrations"
        echo "  down            - Rollback last migration"
        echo "  status          - Show current migration status"
        exit 1
        ;;
esac
