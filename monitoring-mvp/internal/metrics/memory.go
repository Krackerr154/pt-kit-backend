package metrics

import (
	"fmt"
	"time"

	"github.com/shirou/gopsutil/v3/mem"
)

// MemoryStats holds memory metrics
type MemoryStats struct {
	Timestamp     time.Time `json:"timestamp"`
	AgentID       string    `json:"agent_id"`
	Total         uint64    `json:"total_bytes"`
	Available     uint64    `json:"available_bytes"`
	Used          uint64    `json:"used_bytes"`
	UsedPercent   float64   `json:"used_percent"`
	Free          uint64    `json:"free_bytes"`
	Buffers       uint64    `json:"buffers_bytes,omitempty"`
	Cached        uint64    `json:"cached_bytes,omitempty"`
	SwapTotal     uint64    `json:"swap_total_bytes,omitempty"`
	SwapUsed      uint64    `json:"swap_used_bytes,omitempty"`
	SwapFree      uint64    `json:"swap_free_bytes,omitempty"`
	SwapUsedPercent float64 `json:"swap_used_percent,omitempty"`
}

// CollectMemory collects memory metrics from the system
func CollectMemory(agentID string) (*MemoryStats, error) {
	stats := &MemoryStats{
		Timestamp: time.Now(),
		AgentID:   agentID,
	}
	
	// Get virtual memory info
	vmem, err := mem.VirtualMemory()
	if err != nil {
		return nil, fmt.Errorf("failed to get virtual memory: %w", err)
	}
	
	stats.Total = vmem.Total
	stats.Available = vmem.Available
	stats.Used = vmem.Used
	stats.UsedPercent = vmem.UsedPercent
	stats.Free = vmem.Free
	
	// Get pagefile/swap info if available
	swap, err := mem.SwapMemory()
	if err == nil {
		stats.SwapTotal = swap.Total
		stats.SwapUsed = swap.Used
		stats.SwapFree = swap.Free
		stats.SwapUsedPercent = swap.UsedPercent
	}
	
	return stats, nil
}
