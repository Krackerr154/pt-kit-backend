-- Create subagent_metrics table (non-hypertable for periodic health checks)
CREATE TABLE IF NOT EXISTS subagent_metrics (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    subagent_name TEXT NOT NULL,
    subagent_type TEXT NOT NULL,
    host_id TEXT,
    status TEXT,
    active_tasks INTEGER DEFAULT 0,
    uptime_seconds BIGINT,
    error_count INTEGER DEFAULT 0,
    last_heartbeat TIMESTAMPTZ,
    metadata JSONB,
    CONSTRAINT valid_status CHECK (status IN ('active', 'inactive', 'error', 'pending'))
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_subagent_metrics_time ON subagent_metrics(time DESC);
CREATE INDEX IF NOT EXISTS idx_subagent_metrics_name ON subagent_metrics(subagent_name);
CREATE INDEX IF NOT EXISTS idx_subagent_metrics_status ON subagent_metrics(status);
CREATE INDEX IF NOT EXISTS idx_subagent_metrics_host_id ON subagent_metrics(host_id);
