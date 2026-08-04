# Multi-stage build for Go Monitoring Agent
FROM golang:1.21-alpine AS builder

# Install build dependencies
RUN apk add --no-cache git make

# Set working directory
WORKDIR /build

# Copy go.mod and go.sum
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY cmd/ ./cmd/
COPY internal/ ./internal/
COPY pkg/ ./pkg/

# Build binary
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-s -w -extldflags '-static'" \
    -o agent cmd/agent/main.go

# Final stage
FROM alpine:3.18

# Install runtime dependencies
RUN apk add --no-cache ca-certificates docker

# Create non-root user
RUN addgroup -g 1000 monitor && \
    adduser -D -u 1000 -G monitor monitor

# Copy binary from builder
COPY --from=builder /build/agent /usr/local/bin/agent

# Create configuration directory
RUN mkdir -p /etc/monitoring-agent && \
    chown -R monitor:monitor /etc/monitoring-agent

# Switch to non-root user
USER monitor

# Set working directory
WORKDIR /home/monitor

# Expose ports
EXPOSE 8080 9091

# Environment variables with defaults
ENV AGENT_NAME=monitoring-agent
ENV COLLECTION_INTERVAL=10s
ENV LOG_LEVEL=info
ENV DATABASE_URL=""
ENV API_PORT=8080
ENV METRICS_PORT=9091
ENV BUFFER_SIZE=1000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

# Run the agent
ENTRYPOINT ["/usr/local/bin/agent"]
CMD ["--config", "/etc/monitoring-agent/config.yaml"]
