# Go Monitoring Agent

A comprehensive system monitoring agent built in Go that collects CPU, memory, disk, network, and Docker container metrics every 10 seconds.

## Features

### 1. System Metrics Collection
- **CPU**: Total usage, per-core usage, CPU time breakdown (user, system, iowait, idle, irq)
- **Memory**: Total, available, used, free, swap usage with percentage breakdown
- **Disk**: Per-partition metrics including space usage, inode usage for all mounted filesystems
- **Network**: Per-interface statistics including bytes sent/received, packets, errors, dropped packets

### 2. Docker Container Monitoring
- Collects metrics for all running, paused, and stopped containers
- Per-container CPU usage, memory consumption, and PID counts
- Container state tracking and health status

### 3. Timeseries Data Formatting
- All metrics formatted as TimescaleDB-compatible timeseries points
- Tag-based organization by host, agent, metric type, and device/interface
- JSON tag storage for flexible metadata

### 4. Health Check Endpoints
- `/health` - Returns agent health status
- `/ready` - Returns readiness status for Kubernetes/liveness probes

## Architecture

```
cmd/agent/main.go         # Entry point, HTTP server setup, configuration loading
internal/metrics/
    cpu.go                # CPU metrics collection using gopsutil
    memory.go             # Memory metrics collection using gopsutil
    disk.go               # Disk/partition metrics collection using gopsutil
    network.go            # Network interface metrics collection using gopsutil
    docker.go             # Docker container metrics using Docker SDK
    metrics.go            # Core metrics collector and handler infrastructure
    agent.go              # Main agent orchestration and scheduling
pkg/database/timeseries.go # TimescaleDB integration and data formatting
internal/config/config.go  # Configuration management
pkg/database/client.go     # PostgreSQL connection pool management
```

## Dependencies

- **gopsutil** (`github.com/shirou/gopsutil/v3`) - Cross-platform system metrics
- **Docker SDK** (`github.com/docker/docker`) - Docker container API client
- **pgx** (`github.com/jackc/pgx/v5`) - PostgreSQL driver for TimescaleDB
- **Config** - Environment variable-based configuration

## Configuration

Configuration is loaded from environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_NAME` | `monitoring-agent` | Unique identifier for this agent instance |
| `LOG_LEVEL` | `info` | Logging verbosity level |
| `COLLECTION_INTERVAL` | `10s` | Time between metric collections |
| `DATABASE_URL` | (none) | PostgreSQL/TimescaleDB connection string |
| `API_PORT` | `8080` | Port for HTTP health check endpoints |
| `METRICS_PORT` | `9091` | Additional metrics endpoint port |
| `BUFFER_SIZE` | `1000` | Maximum metrics buffer size before flush |

Example:
```bash
export AGENT_NAME="production-server-1"
export DATABASE_URL="postgres://user:pass@localhost:5432/timescaledb"
export COLLECTION_INTERVAL="10s"
export LOG_LEVEL="debug"
./agent
```

## Usage

### Running the Agent

```bash
go run cmd/agent/main.go
```

Or build and run:

```bash
go build -o agent cmd/agent/main.go
./agent
```

### Output Format

The agent outputs complete system snapshots as JSON to stdout every 10 seconds:

```json
{
  "cpu": {
    "timestamp": "2024-01-01T12:00:00Z",
    "agent_id": "monitoring-agent",
    "cpu_usage_percent": 25.5,
    "per_core_usage": [10.2, 15.3, 30.1, 45.7],
    "user_time": 3600.5,
    "system_time": 1200.3,
    "iowait_time": 50.2,
    "idle_time": 25000.0
  },
  "memory": {
    "timestamp": "2024-01-01T12:00:00Z",
    "agent_id": "monitoring-agent",
    "total_bytes": 17179869184,
    "available_bytes": 8589934592,
    "used_bytes": 8589934592,
    "used_percent": 50.0,
    "swap_used_percent": 5.2
  },
  "disk": [...],
  "network": [...],
  "docker": {...}
}
```

### HTTP Endpoints

**Health Check:**
```bash
curl http://localhost:8080/health
```

Response:
```json
{
  "status": "healthy",
  "timestamp": 1704110400000000000
}
```

**Readiness:**
```bash
curl http://localhost:8080/ready
```

Response:
```json
{
  "ready": true,
  "timestamp": 1704110400000000000
}
```

## Database Setup

### Create Hypertable Schema

If you have a TimescaleDB instance, create the required schema:

```sql
-- Create metrics table
CREATE TABLE IF NOT EXISTS metric_data (
    timestamp TIMESTAMPTZ NOT NULL,
    metric TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    tags JSONB NOT NULL
);

-- Convert to hypertable
SELECT create_hypertable('metric_data', 'timestamp');

-- Create indexes
CREATE INDEX ON metric_data(metric);
CREATE INDEX ON metric_data USING GIN(tags);
CREATE INDEX ON metric_data(timestamp, metric);
```

### Query Examples

**Get recent CPU usage:**
```sql
SELECT timestamp, value, tags 
FROM metric_data 
WHERE metric = 'cpu_usage_percent' 
ORDER BY timestamp DESC 
LIMIT 10;
```

**Average memory usage over time:**
```sql
SELECT 
    time_bucket('1 hour', timestamp) AS hour,
    AVG(value) AS avg_memory_used_percent,
    MAX(value) AS max_memory_used_percent,
    MIN(value) AS min_memory_used_percent
FROM metric_data
WHERE metric = 'memory_usage_percent'
GROUP BY hour
ORDER BY hour DESC;
```

**Get all metrics for specific host:**
```sql
SELECT * FROM metric_data
WHERE jsonb_path_exists(tags, '$.host ? (@ == "server1")')
ORDER BY timestamp DESC;
```

## Building for Production

```bash
# Build static binary
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o agent cmd/agent/main.go

# Build ARM64 for Raspberry Pi/ARM servers
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -ldflags="-s -w" -o agent cmd/agent/main.go
```

## Docker Support

Ensure the agent has access to Docker socket:

```yaml
# docker-compose.yml for deployment
version: '3.8'
services:
  monitoring-agent:
    image: monitoring-agent:latest
    container_name: monitoring-agent
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - AGENT_NAME=my-server
      - DATABASE_URL=postgres://user:pass@timescaledb:5432/db
      - COLLECTION_INTERVAL=10s
    restart: unless-stopped
```

## Development

### Adding New Metric Types

1. Create struct in appropriate file under `internal/metrics/`
2. Implement `Collect*()` function returning the metrics struct
3. Update `internal/metrics/agent.go` to collect new metrics
4. Add handler in `pkg/database/timeseries.go` if storing in database

### Testing

```bash
# Unit tests
go test ./...

# Integration test with local TimescaleDB
go test -tags=integration ./...
```

## Troubleshooting

### Common Issues

1. **Cannot access Docker socket**
   - Ensure agent runs with proper permissions or in same Docker network
   - Verify socket exists: `ls -la /var/run/docker.sock`

2. **Database connection failures**
   - Check DATABASE_URL format and credentials
   - Verify TimescaleDB extension is enabled: `CREATE EXTENSION IF NOT EXISTS timescaledb;`

3. **Missing per-core metrics**
   - Some containerized environments may not expose all core metrics
   - Check gopsutil compatibility with your OS

4. **High memory usage**
   - Increase BUFFER_SIZE or collection interval
   - Reduce collected partition types in `shouldSkipMountPath()`

## License

MIT License - See LICENSE file for details
