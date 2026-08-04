export interface HostMetrics {
  timestamp: string;
  cpu_percent: number;
  memory_total: number;
  memory_used: number;
  memory_percent: number;
  disk_total: number;
  disk_used: number;
  disk_percent: number;
  network_rx_bytes: number;
  network_tx_bytes: number;
}

export interface ContainerInfo {
  id: string;
  name: string;
  status: string;
  cpu_percent: number;
  memory_usage: number;
  memory_limit: number;
  memory_percent: number;
  network_rx_bytes: number;
  network_tx_bytes: number;
}

export interface DashboardData {
  host: HostMetrics;
  containers: ContainerInfo[];
}
