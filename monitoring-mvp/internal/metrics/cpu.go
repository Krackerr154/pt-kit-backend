package metrics

import (
	"fmt"
	"time"

	"github.com/shirou/gopsutil/v3/cpu"
)

// CPUStats holds CPU metrics
type CPUStats struct {
	Timestamp       time.Time `json:"timestamp"`
	AgentID         string    `json:"agent_id"`
	CPUUsagePercent float64   `json:"cpu_usage_percent"`
	PerCoreUsage    []float64 `json:"per_core_usage,omitempty"`
	UserTime        float64   `json:"user_time,omitempty"`
	SystemTime      float64   `json:"system_time,omitempty"`
	IOWaitTime      float64   `json:"iowait_time,omitempty"`
	IdleTime        float64   `json:"idle_time,omitempty"`
	IRQTime         float64   `json:"irq_time,omitempty"`
	SoftIRQTime     float64   `json:"soft_irq_time,omitempty"`
	ContextSwitches uint64    `json:"context_switches,omitempty"`
	Interrupts      uint64    `json:"interrupts,omitempty"`
}

// CollectCPU collects CPU metrics from the system
func CollectCPU(agentID string) (*CPUStats, error) {
	stats := &CPUStats{
		Timestamp: time.Now(),
		AgentID:   agentID,
	}
	
	// Get CPU percentage
	usage, err := cpu.Percent(0, false)
	if err != nil {
		return nil, fmt.Errorf("failed to get CPU percentage: %w", err)
	}
	
	if len(usage) > 0 {
		stats.CPUUsagePercent = usage[0]
	} else {
		stats.CPUUsagePercent = 0
	}
	
	// Get per-core usage if available
	allUsage, err := cpu.Percent(true, false)
	if err == nil && len(allUsage) > 0 {
		stats.PerCoreUsage = allUsage
	}
	
	// Get CPU times (aggregate for all cores)
	times, err := cpu.Times(false)
	if err == nil && len(times) > 0 {
		cpuTimes := times[0]
		stats.UserTime = cpuTimes.User
		stats.SystemTime = cpuTimes.System
		stats.IOWaitTime = cpuTimes.Iowait
		stats.IdleTime = cpuTimes.Idle
		stats.IRQTime = cpuTimes.Irq
		stats.SoftIRQTime = cpuTimes.Softirq
	}
	
	// Get hardware counters (context switches, interrupts)
	counters, err := cpu.Counts(false)
	if err == nil {
		stats.ContextSwitches = counters.ContextSwitches
		stats.Interrupts = counters.Interrupts
	}
	
	return stats, nil
}
