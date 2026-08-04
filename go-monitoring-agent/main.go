package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/shirou/gopsutil/cpu"
	"github.com/shirou/gopsutil/disk"
	"github.com/shirou/gopsutil/host"
	"github.com/shirou/gopsutil/mem"
	"github.com/shirou/gopsutil/net"
)

// HostMetrics represents system host metrics
type HostMetrics struct {
	CPUPercent    float64   `json:"cpu_percent"`
	MemoryTotal   uint64    `json:"memory_total"`
	MemoryUsed    uint64    `json:"memory_used"`
	MemoryPercent float64   `json:"memory_percent"`
	DiskTotal     uint64    `json:"disk_total"`
	DiskUsed      uint64    `json:"disk_used"`
	DiskPercent   float64   `json:"disk_percent"`
	NetworkRX     uint64    `json:"network_rx"`
	NetworkTX     uint64    `json:"network_tx"`
	Timestamp     time.Time `json:"timestamp"`
}

// ContainerMetrics represents per-container metrics
type ContainerMetrics struct {
	ID            string  `json:"container_id"`
	Name          string  `json:"container_name"`
	Image         string  `json:"image"`
	Status        string  `json:"status"`
	CPUPercent    float64 `json:"cpu_percent"`
	MemoryUsage   uint64  `json:"memory_usage"`
	MemoryLimit   uint64  `json:"memory_limit"`
	MemoryPercent float64 `json:"memory_percent"`
	NetworkRX     uint64  `json:"network_rx"`
	NetworkTX     uint64  `json:"network_tx"`
}

// MetricsResponse represents the response structure for metrics endpoint
type MetricsResponse struct {
	Host       *HostMetrics        `json:"host,omitempty"`
	Containers []*ContainerMetrics `json:"containers,omitempty"`
	Error      string              `json:"error,omitempty"`
	Timestamp  time.Time           `json:"timestamp"`
}

// DockerClientInterface interface for mock testing
type DockerClientInterface interface {
	ListContainers() ([]*ContainerMetrics, error)
}

// MockDockerClient for when Docker is not available
type MockDockerClient struct{}

func (m *MockDockerClient) ListContainers() ([]*ContainerMetrics, error) {
	return nil, nil
}

// RealDockerClient for actual Docker integration
type RealDockerClient struct {
	enabled bool
}

func (d *RealDockerClient) ListContainers() ([]*ContainerMetrics, error) {
	if !d.enabled {
		return nil, nil
	}
	
	// Docker integration would go here
	// This is a placeholder - in production you'd use the Docker SDK
	log.Println("Docker metrics collection is enabled but not implemented in this demo")
	return nil, nil
}

var (
	metricsMutex sync.RWMutex
	lastMetrics  *HostMetrics
	dockerClient DockerClientInterface
	shutdownChan chan struct{}
	wg           sync.WaitGroup
)

// collectMetrics collects CPU, memory, disk, and network statistics using gopsutil
func collectMetrics() (*HostMetrics, error) {
	// CPU statistics
	cpuPercent, err := cpu.Percent(1*time.Second, false)
	if err != nil {
		log.Printf("Error getting CPU percent: %v", err)
	} else if len(cpuPercent) > 0 {
		cpuPercent = cpuPercent[:1] // Use first value
	} else {
		cpuPercent = []float64{0}
	}

	// Memory statistics
	memStats, err := mem.VirtualMemory()
	if err != nil {
		log.Printf("Error getting memory stats: %v", err)
		return nil, err
	}

	// Disk statistics
	diskStats, err := disk.Usage("/")
	if err != nil {
		log.Printf("Error getting disk stats: %v", err)
		return nil, err
	}

	// Network statistics
	ioStats, err := net.IOCounters(false)
	if err != nil {
		log.Printf("Error getting network stats: %v", err)
		return nil, err
	}

	var rxBytes, txBytes uint64
	if len(ioStats) > 0 {
		rxBytes = ioStats[0].BytesRecv
		txBytes = ioStats[0].BytesSent
	}

	hostInfo, _ := host.Info()

	metrics := &HostMetrics{
		CPUPercent:    cpuPercent[0],
		MemoryTotal:   memStats.Total,
		MemoryUsed:    memStats.Used,
		MemoryPercent: memStats.UsedPercent,
		DiskTotal:     diskStats.Total,
		DiskUsed:      diskStats.Used,
		DiskPercent:   diskStats.UsedPercent,
		NetworkRX:     rxBytes,
		NetworkTX:     txBytes,
		Timestamp:     time.Now(),
	}

	_ = hostInfo // Use hostInfo if needed

	return metrics, nil
}

// collectDockerMetrics collects Docker container information
func collectDockerMetrics() ([]*ContainerMetrics, error) {
	if dockerClient == nil {
		return nil, nil
	}

	return dockerClient.ListContainers()
}

// metricsHandler handles /metrics/host endpoint
func metricsHandler(w http.ResponseWriter, r *http.Request) {
	metrics, err := collectMetrics()
	if err != nil {
		http.Error(w, "Failed to collect metrics", http.StatusInternalServerError)
		return
	}

	metricsMutex.Lock()
	lastMetrics = metrics
	metricsMutex.Unlock()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(metrics)
}

// dockerHandler handles /metrics/docker endpoint
func dockerHandler(w http.ResponseWriter, r *http.Request) {
	if dockerClient == nil {
		http.Error(w, "Docker client not available", http.StatusServiceUnavailable)
		return
	}

	containers, err := collectDockerMetrics()
	if err != nil {
		http.Error(w, "Failed to collect Docker metrics", http.StatusInternalServerError)
		return
	}

	response := MetricsResponse{
		Containers: containers,
		Timestamp:  time.Now(),
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

// healthHandler handles /health endpoint
func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("OK"))
}

// startMetricsCollector starts the background metrics collection goroutine
func startMetricsCollector() {
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-shutdownChan:
			log.Println("Stopping metrics collector...")
			return
		case <-ticker.C:
			go func() {
				metrics, err := collectMetrics()
				if err != nil {
					log.Printf("Error collecting metrics: %v", err)
					return
				}
				
				metricsMutex.Lock()
				lastMetrics = metrics
				metricsMutex.Unlock()
			}()
		}
	}
}

// setupSignalHandler sets up signal handling for graceful shutdown
func setupSignalHandler() {
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		sig := <-sigChan
		log.Printf("Received signal: %v, initiating graceful shutdown...", sig)
		close(shutdownChan)
		
		// Wait for goroutines to finish with timeout
		done := make(chan struct{})
		go func() {
			wg.Wait()
			close(done)
		}()

		select {
		case <-done:
			log.Println("All goroutines finished gracefully")
		case <-time.After(30 * time.Second):
			log.Println("Shutdown timeout reached, forcing termination")
		}
	}()
}

// initDockerClient initializes Docker client
func initDockerClient(enabled bool) {
	if enabled {
		dockerClient = &RealDockerClient{enabled: true}
		log.Println("Docker client initialized successfully")
	} else {
		dockerClient = &MockDockerClient{}
	}
}

func main() {
	// Configuration from environment variables
	port := os.Getenv("METRICS_PORT")
	if port == "" {
		port = "8080"
	}
	
	dockerEnabled := os.Getenv("DOCKER_ENABLED") == "true"
	
	// Initialize Docker client
	initDockerClient(dockerEnabled)

	// Initialize shutdown channel
	shutdownChan = make(chan struct{})
	
	// Set up signal handler
	setupSignalHandler()

	// Start metrics collector
	wg.Add(1)
	go func() {
		defer wg.Done()
		startMetricsCollector()
	}()

	// Setup HTTP routes
	http.HandleFunc("/metrics/host", metricsHandler)
	http.HandleFunc("/metrics/docker", dockerHandler)
	http.HandleFunc("/health", healthHandler)

	// Create HTTP server with graceful shutdown
	server := &http.Server{
		Addr:         ":" + port,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Graceful shutdown handler
	go func() {
		<-shutdownChan
		log.Println("HTTP server shutting down...")
		
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		
		if err := server.Shutdown(ctx); err != nil {
			log.Printf("HTTP server shutdown error: %v", err)
		}
	}()

	log.Printf("Starting metrics server on port %s", port)
	log.Printf("Docker monitoring: %v", dockerEnabled)
	
	if err := server.ListenAndServe(); err != http.ErrServerClosed {
		log.Fatalf("Server failed: %v", err)
	}
	
	log.Println("Server stopped gracefully")
}
