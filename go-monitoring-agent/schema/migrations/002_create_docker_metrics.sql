-- Create docker_metrics table (hypertable)
CREATE TABLE IF NOT EXISTS docker_metrics (
    time TIMESTAMPTZ NOT NULL,
    container_name TEXT NOT NULL,
    id TEXT NOT NULL,
    status TEXT,
    cpu_percent FLOAT,
    memory_usage BIGINT,
    memory_limit BIGINT,
    block_io_read BIGINT,
    block_io_write BIGINT,
    net_rx BIGINT,
    net_tx BIGINT
);

-- Convert to hypertable
SELECT create_hypertable('docker_metrics', 'time');

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_docker_metrics_container_name ON docker_metrics(container_name);
CREATE INDEX IF NOT EXISTS idx_docker_metrics_id ON docker_metrics(id);
CREATE INDEX IF NOT EXISTS idx_docker_metrics_time_container ON docker_metrics(time DESC, container_name);
CREATE INDEX IF NOT EXISTS idx_docker_metrics_status ON docker_metrics(status);
