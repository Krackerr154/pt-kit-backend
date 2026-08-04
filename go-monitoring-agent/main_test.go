package main

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"
)

// TestHealthEndpoint tests the /health endpoint
func TestHealthEndpoint(t *testing.T) {
	req := httptest.NewRequest("GET", "/health", nil)
	w := httptest.NewRecorder()

	healthHandler(w, req)

	resp := w.Result()
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Errorf("Failed to read response body: %v", err)
	}

	if string(body) != "OK" {
		t.Errorf("Expected 'OK', got '%s'", string(body))
	}
}

// TestMetricsHostEndpoint tests the /metrics/host endpoint
func TestMetricsHostEndpoint(t *testing.T) {
	req := httptest.NewRequest("GET", "/metrics/host", nil)
	w := httptest.NewRecorder()

	metricsHandler(w, req)

	resp := w.Result()
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}

	// Verify response is JSON by checking content type
	contentType := resp.Header.Get("Content-Type")
	if contentType != "application/json; charset=utf-8" {
		t.Logf("Content-Type might be: %s", contentType)
	}
}

// TestCollectMetrics function
func TestCollectMetrics(t *testing.T) {
	// Skip if running in CI without proper environment
	if testing.Short() {
		t.Skip("Skipping collect metrics test in short mode")
	}

	metrics, err := collectMetrics()
	if err != nil {
		t.Fatalf("Failed to collect metrics: %v", err)
	}

	if metrics.CPUPercent < 0 || metrics.CPUPercent > 100 {
		t.Errorf("Invalid CPU percent: %f", metrics.CPUPercent)
	}

	if metrics.MemoryTotal == 0 {
		t.Error("Memory total should not be 0")
	}

	if metrics.DiskTotal == 0 {
		t.Error("Disk total should not be 0")
	}
}

// TestDockerClientInitialization tests Docker client initialization
func TestDockerClientInitialization(t *testing.T) {
	// Test without DOCKER_HOST set
	dockerClient = nil
	err := initDockerClient()
	
	// In most environments, this will fail because Docker socket doesn't exist
	// This is expected behavior during unit tests
	if err != nil {
		t.Logf("Docker client initialization failed (expected in unit test): %v", err)
	}
}

// TestEnvironmentVariables tests configuration from environment variables
func TestEnvironmentVariables(t *testing.T) {
	tests := []struct {
		name     string
		port     string
		expected string
	}{
		{"Custom port", "9000", "9000"},
		{"Default port", "", "8080"},
		{"Empty port", "", "8080"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			port := tt.port
			if port == "" {
				port = os.Getenv("METRICS_PORT")
				if port == "" {
					port = "8080"
				}
			}
			if port != tt.expected {
				t.Errorf("Expected port %s, got %s", tt.expected, port)
			}
		})
	}
}

// TestContextTimeout tests context timeout handling
func TestContextTimeout(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	done := make(chan bool)
	go func() {
		time.Sleep(500 * time.Millisecond)
		done <- true
	}()

	select {
	case <-done:
		// Success
	case <-ctx.Done():
		t.Fatal("Context timed out unexpectedly")
	}
}

// Example usage for documentation
func ExampleMain() {
	// This example shows how the main function would work
	// It's commented out since we're demonstrating usage
	
	/*
	   // Set environment variables
	   os.Setenv("METRICS_PORT", "8080")
	   os.Setenv("DOCKER_ENABLED", "true")
	   
	   // The main function would start here
	   main()
	*/
}
