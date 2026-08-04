# Go Monitoring Agent

A comprehensive monitoring agent written in Go that provides real-time system metrics, Docker container statistics, and WebSocket-based streaming capabilities.

## Features

### 1. System Metrics Collection (using gopsutil)
- **CPU Usage**: Real-time CPU percentage usage
- **Memory Statistics**: Total, used memory, and usage percentage
- **Disk Statistics**: Total disk space, used space, and usage percentage
- **Network Statistics**: Received (RX) and transmitted (TX) bytes

### 2. Docker Integration
- List all running containers
- Per-container CPU usage percentage
- Per-container memory usage, limit, and percentage
- Per-container network RX/TX statistics
- Container status and image information

### 3. HTTP REST API Endpoints
- `GET /metrics/host` - Host system metrics
- `GET /metrics/docker` - Docker container metrics
- `GET /health` - Health check endpoint
- `WS /ws` - WebSocket for real-time streaming

### 4. Background Metrics Collection
- Automatic metrics collection every 10 seconds
- Thread-safe metrics storage using mutex
- Goroutine-based concurrent processing

### 5. Graceful Shutdown
- Signal handling (SIGINT, SIGTERM)
- Context-aware HTTP server shutdown
- Controlled cleanup of background goroutines

### 6. Environment Configuration
- All configuration via environment variables
- Configurable metrics port
- Optional Docker integration toggle
- Customizable collection intervals

## Prerequisites

- Go 1.19 or later
- Docker (optional, for container monitoring)
- Linux/macOS/Windows support

## Installation

### 1. Clone or Create Project
```bash
mkdir -p go-monitoring-agent
cd go-monitoring-agent
go mod init go-monitoring-agent
```

### 2. Install Dependencies
```bash
go get github.com/shirou/gopsutil/cpu
go get github.com/shirou/gopsutil/disk
go get github.com/shirou/gopsutil/host
go get github.com/shirou/gopsutil/mem
go get github.com/shirou/gopsutil/net
go get github.com/docker/docker/client
go get github.com/gorilla/websocket
```

### 3. Copy Source Files
Copy the following files to your project directory:
- `main.go` - Main application logic
- `websocket.go` - WebSocket handler
- `.env.example` - Environment variable template

### 4. Build Binary
```bash
go build -o go-monitoring-agent main.go websocket.go
```

### 5. Run Application
```bash
./go-monitoring-agent
```

Or with custom configuration:
```bash
METRICS_PORT=9000 DOCKER_ENABLED=true ./go-monitoring-agent
```

## Configuration

Set environment variables before running:

| Variable | Default | Description |
|----------|---------|-------------|
| `METRICS_PORT` | `8080` | HTTP server port |
| `DOCKER_ENABLED` | `false` | Enable Docker metrics collection |
| `DOCKER_HOST` | (empty) | Docker socket path |
| `COLLECTION_INTERVAL` | `10` | Metrics collection interval in seconds |

Example:
```bash
export METRICS_PORT=8080
export DOCKER_ENABLED=true
./go-monitoring-agent
```

## API Endpoints

### Health Check
```bash
curl http://localhost:8080/health
# Response: OK
```

### Host Metrics
```bash
curl http://localhost:8080/metrics/host
```

**Response:**
```json
{
  "cpu_percent": 12.5,
  "memory_total": 17179869184,
  "memory_used": 10737418240,
  "memory_percent": 62.5,
  "disk_total": 500000000000,
  "disk_used": 250000000000,
  "disk_percent": 50.0,
  "network_rx": 1073741824,
  "network_tx": 536870912,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Docker Metrics
```bash
curl http://localhost:8080/metrics/docker
```

**Response:**
```json
{
  "containers": [
    {
      "container_id": "abc123def456",
      "container_name": "/my_container",
      "image": "nginx:latest",
      "status": "running",
      "cpu_percent": 5.2,
      "memory_usage": 53687091,
      "memory_limit": 536870912,
      "memory_percent": 10.0,
      "network_rx": 10240,
      "network_tx": 20480
    }
  ],
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### WebSocket Connection
```javascript
// JavaScript example
const ws = new WebSocket('ws://localhost:8080/ws');

ws.onopen = () => {
  console.log('WebSocket connection established');
};

ws.onmessage = (event) => {
  const metrics = JSON.parse(event.data);
  console.log('Received metrics:', metrics);
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};

ws.onclose = () => {
  console.log('WebSocket connection closed');
};
```

## Architecture

### Components

1. **HostMetrics Struct**
   - Stores all host-level metrics
   - Fields: CPU%, Memory (total/used/%), Disk (%), Network (RX/TX)

2. **ContainerMetrics Struct**
   - Stores per-container metrics from Docker
   - Fields: ID, Name, Image, Status, CPU%, Memory (usage/limit/%), Network (RX/TX)

3. **collectMetrics() Function**
   - Runs every 10 seconds
   - Uses gopsutil library for OS-independent metrics
   - Returns HostMetrics struct

4. **collectDockerMetrics() Function**
   - Integrates with Docker daemon via docker-go SDK
   - Lists all containers
   - Fetches per-container resource usage

5. **HTTP Handlers**
   - `/metrics/host`: Returns system metrics
   - `/metrics/docker`: Returns container metrics
   - `/health`: Simple health check
   - `/ws`: WebSocket endpoint for real-time updates

6. **Signal Handler**
   - Catches SIGINT (Ctrl+C) and SIGTERM
   - Triggers graceful shutdown
   - Waits for goroutines with timeout

## Testing

### Local Build and Test

```bash
# Build the binary
go build -v -o go-monitoring-agent .

# Run the binary
./go-monitoring-agent

# Test endpoints
curl http://localhost:8080/health
curl http://localhost:8080/metrics/host
curl http://localhost:8080/metrics/docker

# Test in background
./go-monitoring-agent &
PID=$!
sleep 2
curl http://localhost:8080/metrics/host
kill $PID
```

### Unit Testing (Optional)

```bash
go test -v ./...
```

### Docker Deployment (Optional)

```dockerfile
FROM golang:1.19-alpine AS builder
RUN apk add --no-cache git gcc musl-dev
WORKDIR /app
COPY go.mod .
RUN go mod download
COPY . .
RUN go build -o agent .

FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /root/
COPY --from=builder /app/agent .
EXPOSE 8080
CMD ["./agent"]
```

Build and run:
```bash
docker build -t go-monitoring-agent .
docker run -p 8080:8080 -e DOCKER_ENABLED=true --privileged go-monitoring-agent
```

## Troubleshooting

### Docker permissions issue
If you get permission errors accessing Docker socket:
```bash
sudo usermod -aG docker $USER
# Then logout and login again
```

### Port already in use
Change the port:
```bash
export METRICS_PORT=9000
./go-monitoring-agent
```

### Metrics not updating
Check if metrics collection is running by watching logs:
```bash
./go-monitoring-agent 2>&1 | grep -i "metric"
```

## Security Considerations

1. **Production Deployment**
   - Use HTTPS in production
   - Implement authentication on endpoints
   - Restrict WebSocket origins
   - Use proper firewall rules

2. **Docker Socket Access**
   - Mount Docker socket only when needed
   - Use rootless Docker mode if available
   - Monitor Docker API calls

3. **Resource Limits**
   - Set memory limits in production
   - Configure log rotation
   - Monitor the agent's own resource usage

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
