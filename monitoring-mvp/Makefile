# Makefile for Go Monitoring Agent

.PHONY: all build test clean docker-build docker-run docs

# Version info
VERSION := 1.0.0
BUILD_TIME := $(shell date -u '+%Y-%m-%d %H:%M:%S UTC')
GIT_COMMIT := $(shell git rev-parse HEAD 2>/dev/null || echo "unknown")

# Build flags
LDFLAGS := -s -w
EXTRA_LDFLAGS := -X main.BuildVersion=$(VERSION) -X main.BuildTime=$(BUILD_TIME) -X main.GitCommit=$(GIT_COMMIT)

# Default target
all: test build

# Build the agent binary
build:
	@echo "Building monitoring-agent..."
	go build -ldflags "$(LDFLAGS) $(EXTRA_LDFLAGS)" -o bin/monitoring-agent cmd/agent/main.go
	@echo "Build complete! Binary: bin/monitoring-agent"

# Build static binary (for Alpine containers)
build-static:
	@echo "Building static binary..."
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
		-ldflags="$(LDFLAGS) $(EXTRA_LDFLAGS) -extldflags '-static'" \
		-o bin/monitoring-agent-linux-amd64 cmd/agent/main.go

# Cross-compilation for multiple architectures
build-cross:
	@echo "Cross-building binaries..."
	
	# Linux AMD64
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
		-ldflags="$(LDFLAGS) $(EXTRA_LDFLAGS)" \
		-o bin/monitoring-agent-linux-amd64 cmd/agent/main.go
	
	# Linux ARM64
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build \
		-ldflags="$(LDFLAGS) $(EXTRA_LDFLAGS)" \
		-o bin/monitoring-agent-linux-arm64 cmd/agent/main.go
	
	# macOS AMD64
	CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build \
		-ldflags="$(LDFLAGS) $(EXTRA_LDFLAGS)" \
		-o bin/monitoring-agent-darwin-amd64 cmd/agent/main.go
	
	# macOS ARM64
	CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build \
		-ldflags="$(LDFLAGS) $(EXTRA_LDFLAGS)" \
		-o bin/monitoring-agent-darwin-arm64 cmd/agent/main.go
	
	@echo "Cross-build complete!"

# Run tests
test:
	@echo "Running tests..."
	go test -v -cover ./...

# Run tests with race detector
test-race:
	@echo "Running tests with race detector..."
	go test -race -v -cover ./...

# Clean build artifacts
clean:
	@echo "Cleaning up..."
	rm -rf bin/
	rm -f *.out
	@echo "Clean complete!"

# Docker build
docker-build:
	@echo "Building Docker image..."
	docker build -t monitoring-agent:$(VERSION) .
	docker tag monitoring-agent:$(VERSION) monitoring-agent:latest

# Docker run (development)
docker-run:
	@echo "Running agent in container..."
	docker run --rm \
		--name monitoring-agent \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-e AGENT_NAME=local-agent \
		-e DATABASE_URL=postgres://localhost:5432/timescaledb \
		-p 8080:8080 \
		monitoring-agent:latest

# Docker compose up
docker-compose-up:
	@echo "Starting Docker Compose..."
	docker-compose up -d

# Docker compose down
docker-compose-down:
	@echo "Stopping Docker Compose..."
	docker-compose down

# Install dependencies
deps:
	@echo "Installing dependencies..."
	go mod download
	go mod tidy

# Format code
fmt:
	@echo "Formatting code..."
	go fmt ./...

# Lint
lint:
	@echo "Linting code..."
	golangci-lint run ./...

# Run the agent locally
run:
	@echo "Running agent locally..."
	go run cmd/agent/main.go

# Generate documentation
docs:
	@echo "Generating documentation..."
	go doc ./... > docs/api.md

# Create release artifacts
release: build-cross
	@echo "Creating release artifacts..."
	mkdir -p release
	cp bin/* release/
	tar czvf monitoring-agent-linux-amd64.tar.gz bin/monitoring-agent-linux-amd64
	tar czvf monitoring-agent-linux-arm64.tar.gz bin/monitoring-agent-linux-arm64
	tar czvf monitoring-agent-darwin-amd64.tar.gz bin/monitoring-agent-darwin-amd64
	tar czvf monitoring-agent-darwin-arm64.tar.gz bin/monitoring-agent-darwin-arm64

# Check dependencies security vulnerabilities
security-check:
	@echo "Checking dependencies for vulnerabilities..."
	govulncheck ./...

# Show current version
version:
	@echo "Monitoring Agent Version: $(VERSION)"

# Setup TimescaleDB schema
setup-db:
	@echo "Setting up TimescaleDB schema..."
	@echo "Make sure timescaledb is enabled on your PostgreSQL instance"
	@psql $(DATABASE_URL) -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
	@echo "Schema setup complete. See README for table creation instructions."

# Validate imports
validate-imports:
	@echo "Validating imports..."
	goimports -l -local github.com/monitoring-mvp/agent ./cmd ./internal ./pkg

# Help
help:
	@echo "Go Monitoring Agent - Available targets:"
	@echo "  make build              - Build the agent binary"
	@echo "  build-static            - Build static binary for containers"
	@echo "  build-cross             - Build for multiple platforms"
	@echo "  test                    - Run tests"
	@echo "  test-race               - Run tests with race detector"
	@echo "  clean                   - Remove build artifacts"
	@echo "  docker-build            - Build Docker image"
	@echo "  docker-run              - Run Docker container"
	@echo "  docker-compose-up       - Start docker-compose stack"
	@echo "  deps                    - Install dependencies"
	@echo "  fmt                     - Format code"
	@echo "  lint                    - Run linter"
	@echo "  run                     - Run locally (development)"
	@echo "  security-check          - Check for vulnerabilities"
	@echo "  help                    - Show this help message"
