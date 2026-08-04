-- Continuous Aggregates for Time-Series Data

-- Host Metrics: 1-minute averages and max values
CREATE MATERIALIZED VIEW IF NOT EXISTS host_metrics_1m
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 minute', time) AS bucket,
    hostname,
    avg(cpu_percent) as avg_cpu_percent,
    max(cpu_percent) as max_cpu_percent,
    avg(memory_percent) as avg_memory_percent,
    max(memory_percent) as max_memory_percent,
    avg(disk_percent) as avg_disk_percent,
    max(disk_percent) as max_disk_percent,
    avg(CAST(network_rx_bytes AS DOUBLE PRECISION)) as avg_network_rx_bytes,
    max(CAST(network_rx_bytes AS BIGINT)) as max_network_rx_bytes,
    avg(CAST(network_tx_bytes AS DOUBLE PRECISION)) as avg_network_tx_bytes,
    max(CAST(network_tx_bytes AS BIGINT)) as max_network_tx_bytes
FROM host_metrics
GROUP BY bucket, hostname;

-- Host Metrics: 5-minute averages and max values
CREATE MATERIALIZED VIEW IF NOT EXISTS host_metrics_5m
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('5 minutes', time) AS bucket,
    hostname,
    avg(cpu_percent) as avg_cpu_percent,
    max(cpu_percent) as max_cpu_percent,
    avg(memory_percent) as avg_memory_percent,
    max(memory_percent) as max_memory_percent,
    avg(disk_percent) as avg_disk_percent,
    max(disk_percent) as max_disk_percent
FROM host_metrics
GROUP BY bucket, hostname;

-- Host Metrics: 1-hour averages and max values
CREATE MATERIALIZED VIEW IF NOT EXISTS host_metrics_1h
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 hour', time) AS bucket,
    hostname,
    avg(cpu_percent) as avg_cpu_percent,
    max(cpu_percent) as max_cpu_percent,
    avg(memory_percent) as avg_memory_percent,
    max(memory_percent) as max_memory_percent,
    avg(disk_percent) as avg_disk_percent,
    max(disk_percent) as max_disk_percent
FROM host_metrics
GROUP BY bucket, hostname;

-- Docker Metrics: 1-minute aggregates
CREATE MATERIALIZED VIEW IF NOT EXISTS docker_metrics_1m
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 minute', time) AS bucket,
    container_name,
    id,
    status,
    avg(cpu_percent) as avg_cpu_percent,
    max(cpu_percent) as max_cpu_percent,
    avg(memory_usage::DOUBLE PRECISION / memory_limit * 100) as avg_memory_percent,
    max(memory_usage::DOUBLE PRECISION / memory_limit * 100) as max_memory_percent,
    sum(block_io_read) as total_block_io_read,
    sum(block_io_write) as total_block_io_write,
    sum(net_rx) as total_net_rx,
    sum(net_tx) as total_net_tx
FROM docker_metrics
GROUP BY bucket, container_name, id, status;

-- Docker Metrics: 5-minute aggregates
CREATE MATERIALIZED VIEW IF NOT EXISTS docker_metrics_5m
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('5 minutes', time) AS bucket,
    container_name,
    id,
    status,
    avg(cpu_percent) as avg_cpu_percent,
    max(cpu_percent) as max_cpu_percent,
    avg(memory_usage::DOUBLE PRECISION / memory_limit * 100) as avg_memory_percent,
    max(memory_usage::DOUBLE PRECISION / memory_limit * 100) as max_memory_percent,
    sum(block_io_read) as total_block_io_read,
    sum(block_io_write) as total_block_io_write,
    sum(net_rx) as total_net_rx,
    sum(net_tx) as total_net_tx
FROM docker_metrics
GROUP BY bucket, container_name, id, status;

-- Docker Metrics: 1-hour aggregates
CREATE MATERIALIZED VIEW IF NOT EXISTS docker_metrics_1h
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 hour', time) AS bucket,
    container_name,
    id,
    status,
    avg(cpu_percent) as avg_cpu_percent,
    max(cpu_percent) as max_cpu_percent,
    avg(memory_usage::DOUBLE PRECISION / memory_limit * 100) as avg_memory_percent,
    max(memory_usage::DOUBLE PRECISION / memory_limit * 100) as max_memory_percent,
    sum(block_io_read) as total_block_io_read,
    sum(block_io_write) as total_block_io_write,
    sum(net_rx) as total_net_rx,
    sum(net_tx) as total_net_tx
FROM docker_metrics
GROUP BY bucket, container_name, id, status;
