'use client';

import { useEffect, useState, useCallback } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { formatBytes, formatNumber } from '@/lib/utils';
import { HostMetrics, ContainerInfo, DashboardData } from '@/types/metrics';

// Types for chart data
interface ChartDataPoint {
  time: string;
  cpu_percent: number;
  memory_percent: number;
  disk_used: number;
  network_rx: number;
  network_tx: number;
}

export default function Home() {
  const [hostMetrics, setHostMetrics] = useState<HostMetrics | null>(null);
  const [containers, setContainers] = useState<ContainerInfo[]>([]);
  const [history, setHistory] = useState<ChartDataPoint[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Fetch initial data from API
  const fetchMetrics = useCallback(async () => {
    try {
      const response = await fetch('http://localhost:8080/metrics/host');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data: HostMetrics = await response.json();
      setHostMetrics(data);
      
      // Fetch containers
      const containersResponse = await fetch('http://localhost:8080/containers');
      if (containersResponse.ok) {
        const containersData: ContainerInfo[] = await containersResponse.json();
        setContainers(containersData);
      }

      // Update history
      setHistory(prev => {
        const newDataPoint: ChartDataPoint = {
          time: new Date(data.timestamp).toLocaleTimeString(),
          cpu_percent: data.cpu_percent,
          memory_percent: data.memory_percent,
          disk_used: data.disk_used,
          network_rx: data.network_rx_bytes,
          network_tx: data.network_tx_bytes,
        };
        return [...prev.slice(-49), newDataPoint]; // Keep last 50 points
      });

      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch metrics');
      setLoading(false);
    }
  }, []);

  // Setup WebSocket connection
  useEffect(() => {
    // Initial fetch
    fetchMetrics();

    // WebSocket connection
    const ws = new WebSocket('ws://localhost:8080/ws');

    ws.onopen = () => {
      setIsConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const data: DashboardData = JSON.parse(event.data);
        
        if (data.host) {
          setHostMetrics(data.host);
          
          setHistory(prev => {
            const newDataPoint: ChartDataPoint = {
              time: new Date(data.host.timestamp).toLocaleTimeString(),
              cpu_percent: data.host.cpu_percent,
              memory_percent: data.host.memory_percent,
              disk_used: data.host.disk_used,
              network_rx: data.host.network_rx_bytes,
              network_tx: data.host.network_tx_bytes,
            };
            return [...prev.slice(-49), newDataPoint];
          });
        }

        if (data.containers) {
          setContainers(data.containers);
        }
      } catch (err) {
        console.error('Error parsing WebSocket message:', err);
      }
    };

    ws.onerror = () => {
      setIsConnected(false);
      setError('WebSocket connection error');
    };

    ws.onclose = () => {
      setIsConnected(false);
    };

    // Cleanup
    return () => {
      ws.close();
    };
  }, [fetchMetrics]);

  // Re-fetch every 10 seconds as a fallback
  useEffect(() => {
    const interval = setInterval(() => {
      fetchMetrics();
    }, 10000);

    return () => clearInterval(interval);
  }, [fetchMetrics]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-blue-400 text-xl">Loading dashboard...</div>
      </div>
    );
  }

  if (error && !hostMetrics) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-red-400 text-xl">Error: {error}</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 text-gray-100 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <header className="mb-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <h1 className="text-2xl sm:text-3xl font-bold text-blue-400">System Monitoring Dashboard</h1>
          <div className="flex items-center gap-2">
            <span className={`w-3 h-3 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'} animate-pulse`}></span>
            <span className="text-sm text-gray-400">
              {isConnected ? 'Live Connection' : 'Disconnected'}
            </span>
          </div>
        </div>
      </header>

      {/* Metrics Cards */}
      <section className="mb-8">
        <h2 className="text-xl sm:text-2xl font-semibold mb-4 text-gray-200">System Metrics</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* CPU Card */}
          <div className="bg-slate-800 rounded-lg p-4 shadow-lg border border-slate-700">
            <h3 className="text-sm font-medium text-gray-400 mb-2">CPU Usage</h3>
            <div className="text-3xl sm:text-4xl font-bold text-green-500 mb-2">
              {hostMetrics ? formatNumber(hostMetrics.cpu_percent, 1) : '--'}%
            </div>
            <p className="text-xs text-gray-500">Real-time CPU utilization</p>
          </div>

          {/* Memory Card */}
          <div className="bg-slate-800 rounded-lg p-4 shadow-lg border border-slate-700">
            <h3 className="text-sm font-medium text-gray-400 mb-2">Memory</h3>
            <div className="text-3xl sm:text-4xl font-bold text-blue-500 mb-2">
              {hostMetrics ? formatNumber(hostMetrics.memory_percent, 1) : '--'}%
            </div>
            <p className="text-xs text-gray-500">
              {hostMetrics ? `${formatBytes(hostMetrics.memory_used)} / ${formatBytes(hostMetrics.memory_total)}` : '-- / --'}
            </p>
          </div>

          {/* Disk Card */}
          <div className="bg-slate-800 rounded-lg p-4 shadow-lg border border-slate-700">
            <h3 className="text-sm font-medium text-gray-400 mb-2">Disk Usage</h3>
            <div className="text-3xl sm:text-4xl font-bold text-purple-500 mb-2">
              {hostMetrics ? formatNumber(hostMetrics.disk_percent, 1) : '--'}%
            </div>
            <p className="text-xs text-gray-500">
              {hostMetrics ? `${formatBytes(hostMetrics.disk_used)} / ${formatBytes(hostMetrics.disk_total)}` : '-- / --'}
            </p>
          </div>

          {/* Network Card */}
          <div className="bg-slate-800 rounded-lg p-4 shadow-lg border border-slate-700">
            <h3 className="text-sm font-medium text-gray-400 mb-2">Network</h3>
            <div className="text-lg sm:text-xl font-bold text-orange-500 mb-1">
              RX: {hostMetrics ? formatBytes(hostMetrics.network_rx_bytes, 1) : '--'}
            </div>
            <div className="text-lg sm:text-xl font-bold text-cyan-500">
              TX: {hostMetrics ? formatBytes(hostMetrics.network_tx_bytes, 1) : '--'}
            </div>
            <p className="text-xs text-gray-500 mt-1">Total transfer</p>
          </div>
        </div>
      </section>

      {/* Real-time Charts */}
      <section className="mb-8">
        <h2 className="text-xl sm:text-2xl font-semibold mb-4 text-gray-200">Real-time Trends</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* CPU/Memory Chart */}
          <div className="bg-slate-800 rounded-lg p-4 shadow-lg border border-slate-700">
            <h3 className="text-lg font-semibold mb-4 text-gray-200">CPU & Memory Usage</h3>
            <div className="h-64 sm:h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={history}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis 
                    dataKey="time" 
                    stroke="#94a3b8" 
                    fontSize={12}
                    tick={{ fill: '#94a3b8' }}
                  />
                  <YAxis 
                    stroke="#94a3b8" 
                    fontSize={12}
                    tick={{ fill: '#94a3b8' }}
                    unit="%"
                  />
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: '#1e293b', 
                      borderColor: '#334155',
                      color: '#f1f5f9'
                    }}
                    labelStyle={{ color: '#94a3b8' }}
                  />
                  <Legend />
                  <Line 
                    type="monotone" 
                    dataKey="cpu_percent" 
                    stroke="#22c55e" 
                    strokeWidth={2}
                    dot={false}
                    name="CPU %"
                  />
                  <Line 
                    type="monotone" 
                    dataKey="memory_percent" 
                    stroke="#3b82f6" 
                    strokeWidth={2}
                    dot={false}
                    name="Memory %"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Disk/Network Chart */}
          <div className="bg-slate-800 rounded-lg p-4 shadow-lg border border-slate-700">
            <h3 className="text-lg font-semibold mb-4 text-gray-200">Disk & Network I/O</h3>
            <div className="h-64 sm:h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={history}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis 
                    dataKey="time" 
                    stroke="#94a3b8" 
                    fontSize={12}
                    tick={{ fill: '#94a3b8' }}
                  />
                  <YAxis 
                    stroke="#94a3b8" 
                    fontSize={12}
                    tick={{ fill: '#94a3b8' }}
                  />
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: '#1e293b', 
                      borderColor: '#334155',
                      color: '#f1f5f9'
                    }}
                    labelStyle={{ color: '#94a3b8' }}
                  />
                  <Legend />
                  <Line 
                    type="monotone" 
                    dataKey="disk_used" 
                    stroke="#a855f7" 
                    strokeWidth={2}
                    dot={false}
                    name="Disk Used"
                  />
                  <Line 
                    type="monotone" 
                    dataKey="network_rx" 
                    stroke="#f97316" 
                    strokeWidth={2}
                    dot={false}
                    name="Network RX"
                  />
                  <Line 
                    type="monotone" 
                    dataKey="network_tx" 
                    stroke="#06b6d4" 
                    strokeWidth={2}
                    dot={false}
                    name="Network TX"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </section>

      {/* Container Table */}
      <section className="mb-8">
        <h2 className="text-xl sm:text-2xl font-semibold mb-4 text-gray-200">Running Containers</h2>
        <div className="bg-slate-800 rounded-lg p-4 shadow-lg border border-slate-700 overflow-x-auto">
          <table className="w-full min-w-[600px]">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="text-left py-3 px-4 text-sm font-medium text-gray-400">Name</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-gray-400">Status</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-gray-400">CPU %</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-gray-400">Memory</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-gray-400">Memory %</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-gray-400">Network RX</th>
                <th className="text-left py-3 px-4 text-sm font-medium text-gray-400">Network TX</th>
              </tr>
            </thead>
            <tbody>
              {containers.length > 0 ? (
                containers.map((container, index) => (
                  <tr key={container.id || index} className="border-b border-slate-700 hover:bg-slate-750">
                    <td className="py-3 px-4 text-sm">{container.name}</td>
                    <td className="py-3 px-4 text-sm">
                      <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                        container.status === 'running' ? 'bg-green-900 text-green-300' :
                        container.status === 'stopped' ? 'bg-red-900 text-red-300' :
                        'bg-yellow-900 text-yellow-300'
                      }`}>
                        {container.status}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-sm text-green-400">
                      {formatNumber(container.cpu_percent, 2)}%
                    </td>
                    <td className="py-3 px-4 text-sm text-blue-400">
                      {formatBytes(container.memory_usage)}
                    </td>
                    <td className="py-3 px-4 text-sm">
                      {formatNumber(container.memory_percent, 2)}%
                    </td>
                    <td className="py-3 px-4 text-sm text-orange-400">
                      {formatBytes(container.network_rx_bytes)}
                    </td>
                    <td className="py-3 px-4 text-sm text-cyan-400">
                      {formatBytes(container.network_tx_bytes)}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-gray-500">
                    No running containers found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-700 pt-4">
        <div className="text-center text-sm text-gray-500">
          <p>System Monitoring Dashboard v1.0.0</p>
          <p className="mt-1">Last updated: {hostMetrics ? new Date(hostMetrics.timestamp).toLocaleString() : 'N/A'}</p>
        </div>
      </footer>
    </div>
  );
}
