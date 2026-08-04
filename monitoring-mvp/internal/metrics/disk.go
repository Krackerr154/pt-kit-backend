package metrics

import (
	"fmt"
	"path/filepath"
	"time"

	"github.com/shirou/gopsutil/v3/disk"
)

// DiskStats holds disk usage metrics for all partitions
type DiskStats struct {
	Timestamp  time.Time                `json:"timestamp"`
	AgentID    string                   `json:"agent_id"`
	Partitions []DiskPartitionStats     `json:"partitions"`
}

// DiskPartitionStats holds disk metrics for a single partition
type DiskPartitionStats struct {
	Device          string  `json:"device"`
	MountPoint      string  `json:"mount_point"`
	Fstype          string  `json:"fstype,omitempty"`
	Opts            string  `json:"opts,omitempty"`
	Total           uint64  `json:"total_bytes"`
	Free            uint64  `json:"free_bytes"`
	Used            uint64  `json:"used_bytes"`
	UsedPercent     float64 `json:"used_percent"`
	BlockUsagePercent float64 `json:"block_usage_percent"`
}

// CollectDisk collects disk metrics from all mounted partitions
func CollectDisk(agentID string) (*DiskStats, error) {
	stats := &DiskStats{
		Timestamp:  time.Now(),
		AgentID:    agentID,
		Partitions: make([]DiskPartitionStats, 0),
	}
	
	// Get disk partitions with IO info
	partitions, err := disk.Partitions(true)
	if err != nil {
		return nil, fmt.Errorf("failed to get disk partitions: %w", err)
	}
	
	for _, partition := range partitions {
		path := filepath.Clean(partition.Mountpoint)
		
		// Skip common mount points we don't care about
		if shouldSkipMountPath(path) {
			continue
		}
		
		usage, err := disk.Usage(path)
		if err != nil {
			fmt.Printf("Warning: failed to get usage for %s: %v\n", path, err)
			continue
		}
		
		partitionStats := DiskPartitionStats{
			Device:          partition.Device,
			MountPoint:      path,
			Fstype:          usage.Fstype,
			Opts:            usage.Opts,
			Total:           usage.Total,
			Free:            usage.Free,
			Used:            usage.Used,
			UsedPercent:     usage.UsedPercent,
			BlockUsagePercent: usage.UsedPercent,
		}
		
		stats.Partitions = append(stats.Partitions, partitionStats)
	}
	
	return stats, nil
}

// shouldSkipMountPath determines if a mount point should be skipped
func shouldSkipMountPath(path string) bool {
	skipPaths := []string{"/proc", "/sys", "/dev", "/run", "/snap", "/boot"}
	
	for _, skip := range skipPaths {
		if path == skip || len(skip) > 1 && filepath.Dir(path) == skip {
			return true
		}
	}
	
	return false
}
