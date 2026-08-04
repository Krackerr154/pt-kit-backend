package metrics

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/monitoring-mvp/agent/internal/config"
)

// Agent represents the main monitoring agent
type Agent struct {
	config    *config.Config
	collector *MetricsCollector
	ctx       context.Context
	cancel    context.CancelFunc
	shutdown  chan struct{}
}

// NewAgent creates a new Agent instance
func NewAgent(cfg *config.Config, collector *MetricsCollector) (*Agent, error) {
	ctx, cancel := context.WithCancel(context.Background())
	
	return &Agent{
		config:    cfg,
		collector: collector,
		ctx:       ctx,
		cancel:    cancel,
		shutdown:  make(chan struct{}),
	}, nil
}

// Run starts the monitoring agent
func (a *Agent) Run(ctx context.Context) error {
	fmt.Printf("Starting %s...\n", a.config.Name)
	fmt.Printf("Collection interval: %v\n", a.config.CollectionInterval)
	
	// Set up ticker for collection
	ticker := time.NewTicker(a.config.CollectionInterval)
	defer ticker.Stop()
	
	// Initial collection
	if err := a.collectAllMetrics(); err != nil {
		log.Printf("Warning: initial collection failed: %v", err)
	}
	
	for {
		select {
		case <-ctx.Done():
			fmt.Println("Context cancelled, stopping agent...")
			a.cleanup()
			return nil
		case <-ticker.C:
			if err := a.collectAllMetrics(); err != nil {
				log.Printf("Error collecting metrics: %v", err)
			}
			
			// Flush buffered metrics periodically
			a.collector.Flush()
			
		case <-a.shutdown:
			fmt.Println("Shutdown signal received")
			a.cleanup()
			return nil
		}
	}
}

// collectAllMetrics collects all system metrics
func (a *Agent) collectAllMetrics() error {
	hostName, _ := os.Hostname()
	
	metrics := map[string]interface{}{
		"cpu":      CollectCPU(a.config.Name),
		"memory":   CollectMemory(a.config.Name),
		"disk":     CollectDisk(a.config.Name),
		"network":  CollectNetwork(a.config.Name),
		"docker":   CollectDocker(a.config.Name, ""),
	}
	
	var combinedData map[string]interface{}
	
	// Collect all successful metrics
	for name, data := range metrics {
		if data == nil {
			continue
		}
		
		if combinedData == nil {
			combinedData = make(map[string]interface{})
		}
		
		jsonBytes, _ := json.Marshal(data)
		var parsed interface{}
		json.Unmarshal(jsonBytes, &parsed)
		combinedData[name] = parsed
		
		// Add to collector buffer
		a.collector.Collect(data)
	}
	
	// Output complete snapshot
	if len(combinedData) > 0 {
		output, err := json.MarshalIndent(combinedData, "", "  ")
		if err == nil {
			fmt.Println(string(output))
		}
	}
	
	return nil
}

// cleanup performs cleanup tasks on shutdown
func (a *Agent) cleanup() {
	fmt.Println("Cleaning up...")
	a.cancel()
	close(a.shutdown)
}

// Stop gracefully stops the agent
func (a *Agent) Stop() error {
	fmt.Println("Stopping agent...")
	close(a.shutdown)
	a.collector.Flush()
	return nil
}

// SetupHTTPServer sets up HTTP endpoints for health checks and metrics
func (a *Agent) SetupHTTPServer(port int) error {
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		response := map[string]interface{}{
			"status":    "healthy",
			"timestamp": time.Now().UnixNano(),
			"agent":     a.config.Name,
		}
		json.NewEncoder(w).Encode(response)
	})
	
	http.HandleFunc("/ready", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		ready := true
		
		response := map[string]interface{}{
			"ready":     ready,
			"timestamp": time.Now().UnixNano(),
			"agent":     a.config.Name,
		}
		
		if !ready {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		json.NewEncoder(w).Encode(response)
	})
	
	addr := fmt.Sprintf(":%d", port)
	fmt.Printf("Starting HTTP server on %s\n", addr)
	
	if err := http.ListenAndServe(addr, nil); err != http.ErrServerClosed {
		return fmt.Errorf("HTTP server error: %w", err)
	}
	
	return nil
}
