-- Create host_metrics table (hypertable)
CREATE TABLE IF NOT EXISTS host_metrics (
    time TIMESTAMPTZ NOT NULL,
    hostname TEXT NOT NULL,
    cpu_percent FLOAT,
    memory_total BIGINT,
    memory_used BIGINT,
    memory_percent FLOAT,
    disk_total BIGINT,
    disk_used BIGINT,
    disk_percent FLOAT,
    network_rx_bytes BIGINT,
    network_tx_bytes BIGINT
);

-- Convert to hypertable
SELECT create_hypertable('host_metrics', 'time');

-- Create index on hostname for faster queries
CREATE INDEX IF NOT EXISTS idx_host_metrics_hostname ON host_metrics(hostname);
CREATE INDEX IF NOT EXISTS idx_host_metrics_time_hostname ON host_metrics(time DESC, hostname);
