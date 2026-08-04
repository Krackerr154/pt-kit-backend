-- Policies: Compression and Retention

-- Set compression policy: Compress data older than 7 days into 1-hour chunks
SELECT add_compression_policy('host_metrics', INTERVAL '7 days');
SELECT add_compression_policy('docker_metrics', INTERVAL '7 days');

-- Set retention policy: Drop data older than 90 days
SELECT add_retention_policy('host_metrics', INTERVAL '90 days');
SELECT add_retention_policy('docker_metrics', INTERVAL '90 days');

-- Optional: Set additional retention policy for subagent_metrics (30 days)
SELECT add_retention_policy('subagent_metrics', INTERVAL '30 days');

-- Validate policies are set correctly
SELECT * FROM job_errors WHERE last_success < NOW() - INTERVAL '1 day';
