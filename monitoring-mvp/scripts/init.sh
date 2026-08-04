#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Initializing Monitoring MVP Environment ===${NC}"

# Create directories
echo -e "${YELLOW}Creating directory structure...${NC}"
mkdir -p cmd/agent
mkdir -p internal/metrics
mkdir -p pkg/database
mkdir -p internal/config
mkdir -p internal/models
mkdir -p scripts
mkdir -p docs

# Initialize Go module if not already done
if [ ! -f "go.mod" ]; then
    echo -e "${YELLOW}Initializing Go module...${NC}"
    go mod init github.com/monitoring-mvp/agent
fi

# Fetch dependencies
echo -e "${YELLOW}Fetching Go dependencies...${NC}"
go mod tidy

# Setup web dependencies
if [ -d "web" ]; then
    echo -e "${YELLOW}Setting up web dependencies...${NC}"
    cd web
    if [ ! -d "node_modules" ]; then
        npm install
    fi
    cd ..
fi

# Create example environment file
if [ ! -f ".env.example" ]; then
    echo -e "${YELLOW}Creating example environment file...${NC}"
    cat > .env.example << EOF
# Application
AGENT_NAME=monitoring-agent-local
LOG_LEVEL=debug
COLLECTION_INTERVAL=10s

# Database
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/monitoring?sslmode=disable

# API
API_PORT=8080
JWT_SECRET=change-this-in-production
EOF
fi

echo -e "${GREEN}=== Environment initialization complete! ===${NC}"
echo ""
echo "To get started:"
echo "  1. Copy .env.example to .env and configure your settings"
echo "  2. Start TimescaleDB: docker-compose up -d timescaledb"
echo "  3. Run the agent: make run"
echo "  4. Or start everything: docker-compose up"
echo ""
