/**
 * Lunar Sintering Simulator - Main Dashboard Application
 * Vanilla JavaScript dashboard logic for real-time telemetry and control
 */

class DashboardApp {
    constructor() {
        this.currentStatus = null;
        this.ws = null;
        this.pollInterval = null;
        this.chart = null;
        this.historyData = [];
        this.maxHistoryPoints = 300; // Store last 300 data points
        
        this.init();
    }

    async init() {
        try {
            // Initialize components
            this.chart = new ChartComponent('telemetryChart');
            
            // Start WebSocket connection for real-time data
            this.connectWebSocket();
            
            // Start polling for status updates as fallback
            this.startStatusPolling();
            
            // Setup event listeners
            this.setupEventListeners();
            
            console.log('Dashboard initialized successfully');
        } catch (error) {
            console.error('Failed to initialize dashboard:', error);
            this.showError('Failed to initialize dashboard');
        }
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/telemetry/`;
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                this.updateConnectionStatus('connected', 'WebSocket Connected');
                console.log('WebSocket connected successfully');
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleTelemetryData(data);
                } catch (error) {
                    console.error('Failed to parse WebSocket message:', error);
                }
            };

            this.ws.onclose = () => {
                this.updateConnectionStatus('disconnected', 'WebSocket Disconnected');
                // Attempt reconnection after 3 seconds
                setTimeout(() => this.connectWebSocket(), 3000);
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.updateConnectionStatus('error', 'WebSocket Error');
            };
        } catch (error) {
            console.error('Failed to create WebSocket:', error);
            this.updateConnectionStatus('error', 'WebSocket Not Available');
        }
    }

    startStatusPolling() {
        this.fetchStatus(); // Initial fetch
        this.pollInterval = setInterval(() => {
            this.fetchStatus();
        }, 1000);
    }

    async fetchStatus() {
        try {
            const response = await fetch('/simulator/status');
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const status = await response.json();
            this.updateDashboard(status);
        } catch (error) {
            console.error('Failed to fetch status:', error);
            this.showError('Failed to fetch simulator status');
        }
    }

    handleTelemetryData(data) {
        // Update UI with real-time telemetry
        this.updateDashboard(data);
        
        // Add to history data
        this.addToHistory(data);
    }

    updateDashboard(status) {
        this.currentStatus = status;
        
        // Update state indicator
        const stateElement = document.getElementById('simState');
        if (stateElement && status.state) {
            stateElement.textContent = status.state;
            stateElement.className = `state-value state-${status.state.toLowerCase()}`;
        }
        
        // Update vacuum pressure
        const vacuumElement = document.getElementById('vacuumPressure');
        if (vacuumElement && typeof status.vacuum_mbar === 'number') {
            vacuumElement.textContent = status.vacuum_mbar.toFixed(2);
        }
        
        // Update surface temperature
        const surfaceTempElement = document.getElementById('surfaceTemp');
        if (surfaceTempElement && typeof status.surface_temp_c === 'number') {
            surfaceTempElement.textContent = status.surface_temp_c.toFixed(1);
        }
        
        // Update bulk temperature
        const bulkTempElement = document.getElementById('bulkTemp');
        if (bulkTempElement && typeof status.bulk_temp_c === 'number') {
            bulkTempElement.textContent = status.bulk_temp_c.toFixed(1);
        }
        
        // Update laser power
        const laserPowerElement = document.getElementById('laserPower');
        if (laserPowerElement && typeof status.laser_power_w === 'number') {
            laserPowerElement.textContent = status.laser_power_w.toFixed(0);
        }
        
        // Update scan speed
        const scanSpeedElement = document.getElementById('scanSpeed');
        if (scanSpeedElement && typeof status.scan_speed_mm_s === 'number') {
            scanSpeedElement.textContent = status.scan_speed_mm_s.toFixed(1);
        }
        
        // Update chart with new data point
        if (this.chart) {
            this.chart.addPoint({
                time: status.virtual_time_s || 0,
                surfaceTemp: status.surface_temp_c || 0,
                bulkTemp: status.bulk_temp_c || 0
            });
        }
        
        // Update fault log if present
        this.updateFaultLog(status.faults || []);
    }

    addToHistory(data) {
        const timestamp = data.virtual_time_s || Date.now() / 1000;
        
        this.historyData.push({
            time: timestamp,
            vacuum: data.vacuum_mbar || 0,
            surfaceTemp: data.surface_temp_c || 0,
            bulkTemp: data.bulk_temp_c || 0,
            laserPower: data.laser_power_w || 0
        });
        
        // Remove oldest entries if we exceed max points
        if (this.historyData.length > this.maxHistoryPoints) {
            this.historyData.shift();
        }
        
        this.renderHistoryTable();
    }

    renderHistoryTable() {
        const tbody = document.getElementById('historyTableBody');
        if (!tbody) return;
        
        tbody.innerHTML = '';
        
        // Show only the last 50 rows in the table
        const displayData = this.historyData.slice(-50).reverse();
        
        displayData.forEach(row => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${row.time.toFixed(1)}</td>
                <td>${row.vacuum.toFixed(2)}</td>
                <td>${row.surfaceTemp.toFixed(1)}</td>
                <td>${row.bulkTemp.toFixed(1)}</td>
                <td>${row.laserPower.toFixed(0)}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    updateFaultLog(faults) {
        const faultList = document.getElementById('faultList');
        const noFaults = document.getElementById('noFaults');
        
        if (!faultList) return;
        
        if (!faults || faults.length === 0) {
            if (noFaults) {
                noFaults.style.display = 'block';
            }
            faultList.innerHTML = '';
            if (noFaults) faultList.appendChild(noFaults);
            return;
        }
        
        if (noFaults) {
            noFaults.style.display = 'none';
        }
        
        faultList.innerHTML = '';
        
        faults.forEach(fault => {
            const faultDiv = document.createElement('div');
            faultDiv.className = 'fault-entry';
            faultDiv.innerHTML = `
                <span class="fault-severity ${fault.severity || 'warning'}">${(fault.severity || 'WARNING').toUpperCase()}</span>
                <span class="fault-message">${fault.message}</span>
                <span class="fault-time">${new Date(fault.timestamp).toLocaleTimeString()}</span>
            `;
            faultList.appendChild(faultDiv);
        });
    }

    setupEventListeners() {
        // Command form submission is handled by controls.js
        // Additional event listeners can be added here
    }

    updateConnectionStatus(status, text) {
        const indicator = document.getElementById('statusIndicator');
        const statusText = document.getElementById('statusText');
        
        if (indicator) {
            indicator.className = 'status-indicator';
            if (status === 'connected') {
                indicator.classList.add('status-connected');
            } else if (status === 'disconnected') {
                indicator.classList.add('status-disconnected');
            } else if (status === 'error') {
                indicator.classList.add('status-error');
            }
        }
        
        if (statusText) {
            statusText.textContent = text;
        }
    }

    showError(message) {
        const errorDiv = document.getElementById('commandError');
        if (errorDiv) {
            errorDiv.textContent = message;
            errorDiv.classList.add('error-visible');
            setTimeout(() => {
                errorDiv.classList.remove('error-visible');
            }, 5000);
        }
    }

    destroy() {
        if (this.ws) {
            this.ws.close();
        }
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
        }
    }
}

// Initialize the dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.dashboardApp = new DashboardApp();
});
