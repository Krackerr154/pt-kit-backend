package metrics

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/monitoring-mvp/agent/internal/config"
)

// MetricType defines the type of metric
type MetricType string

const (
	GaugeMetric     MetricType = "gauge"
	CounterMetric   MetricType = "counter"
	HistogramMetric MetricType = "histogram"
)

// MetricData represents a single metric point
type MetricData struct {
	Timestamp time.Time    `json:"timestamp"`
	AgentID   string       `json:"agent_id"`
	Name      string       `json:"name"`
	Type      MetricType   `json:"type"`
	Value     float64      `json:"value"`
	Labels    map[string]string `json:"labels,omitempty"`
}

// MetricsCollector collects and stores metrics
type MetricsCollector struct {
	mu         sync.RWMutex
	buffer     []interface{}
	bufferSize int
	handlers   []MetricHandler
	config     *config.Config
}

// MetricHandler handles individual metrics
type MetricHandler interface {
	OnMetric(data interface{}) error
}

// NewMetricsCollector creates a new metrics collector
func NewMetricsCollector(bufferSize int) *MetricsCollector {
	return &MetricsCollector{
		buffer:     make([]interface{}, 0, bufferSize),
		bufferSize: bufferSize,
		handlers:   make([]MetricHandler, 0),
		config:     config.DefaultConfig(),
	}
}

// Collect adds data to the collection buffer
func (m *MetricsCollector) Collect(data interface{}) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	
	if len(m.buffer) >= m.bufferSize && len(m.handlers) > 0 {
		m.flushInternal()
	}
	
	m.buffer = append(m.buffer, data)
	return nil
}

// RegisterHandler adds a metric handler
func (m *MetricsCollector) RegisterHandler(handler MetricHandler) {
	m.handlers = append(m.handlers, handler)
}

// Flush sends all buffered data to handlers
func (m *MetricsCollector) Flush() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.flushInternal()
}

// flushInternal processes buffered data through all handlers
func (m *MetricsCollector) flushInternal() {
	for _, data := range m.buffer {
		for _, handler := range m.handlers {
			handler.OnMetric(data)
		}
	}
	m.buffer = m.buffer[:0]
}

// CurrentSnapshot returns a complete system snapshot
func (m *MetricsCollector) CurrentSnapshot() (map[string]interface{}, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	
	snapshot := map[string]interface{}{
		"timestamp":    time.Now().UnixNano(),
		"collector_size": len(m.buffer),
		"handlers":     len(m.handlers),
	}
	
	return snapshot, nil
}

// SetConfig updates collector configuration
func (m *MetricsCollector) SetConfig(cfg *config.Config) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.config = cfg
}
