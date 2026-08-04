package metrics

import (
	"context"
	"fmt"
	"time"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/client"
)

// DockerMetrics holds Docker-specific metrics
type DockerMetrics struct {
	Timestamp         time.Time     `json:"timestamp"`
	AgentID           string        `json:"agent_id"`
	DockerVersion     string        `json:"docker_version,omitempty"`
	ServerVersion     string        `json:"server_version,omitempty"`
	MemTotal          uint64        `json:"mem_total_bytes,omitempty"`
	NumContainers     int           `json:"num_containers"`
	RunningContainers int           `json:"running_containers"`
	PausedContainers  int           `json:"paused_containers"`
	StoppedContainers int           `json:"stopped_containers"`
	Containers        []ContainerStats `json:"containers"`
}

// ContainerStats holds metrics for a single container
type ContainerStats struct {
	ID       string            `json:"id"`
	Name     string            `json:"name"`
	Image    string            `json:"image"`
	State    string            `json:"state"`
	Status   string            `json:"status"`
	Created  int64             `json:"created"`
	Labels   map[string]string `json:"labels,omitempty"`
	CPUPercent float64         `json:"cpu_percent,omitempty"`
	MemoryUsage uint64          `json:"memory_usage_bytes,omitempty"`
	MemoryLimit uint64          `json:"memory_limit_bytes,omitempty"`
	MemoryPercent float64         `json:"memory_percent,omitempty"`
	Pids      int64             `json:"pids_current,omitempty"`
}

// CollectDocker collects Docker container and system metrics
func CollectDocker(agentID, dockerSocketPath string) (*DockerMetrics, error) {
	ctx := context.Background()
	
	// Create Docker client
	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		return nil, fmt.Errorf("failed to create Docker client: %w", err)
	}
	
	stats := &DockerMetrics{
		Timestamp: time.Now(),
		AgentID:   agentID,
	}
	
	// Get system info
	info, err := cli.Info(ctx)
	if err != nil {
		fmt.Printf("Warning: failed to get Docker info: %v\n", err)
		return stats, nil // Return partial data
	}
	
	stats.DockerVersion = info.ServerVersion
	stats.ServerVersion = info.ServerVersion
	stats.MemTotal = info.MemTotal
	
	// Get containers list
	containers, err := cli.ContainerList(ctx, types.ContainerListOptions{All: true})
	if err != nil {
		return nil, fmt.Errorf("failed to list containers: %w", err)
	}
	
	stats.NumContainers = len(containers)
	
	var running, paused, stopped int
	
	// Collect stats for each container
	for _, ctr := range containers {
		containerStats := parseContainerInfo(ctr)
		
		// Update state counts
		switch containerStats.State {
		case "running":
			running++
		case "paused":
			paused++
		default:
			stopped++
		}
		
		stats.Containers = append(stats.Containers, containerStats)
	}
	
	stats.RunningContainers = running
	stats.PausedContainers = paused
	stats.StoppedContainers = stopped
	
	return stats, nil
}

// parseContainerInfo converts ContainerSummary to ContainerStats
func parseContainerInfo(ctr types.Container) ContainerStats {
	cs := ContainerStats{
		ID:       ctr.ID,
		Name:     trimLeadingSlash(ctr.Names[0]),
		Image:    ctr.Image,
		State:    ctr.State,
		Status:   ctr.Status,
		Created:  ctr.Created,
		Labels:   ctr.Labels,
	}
	
	return cs
}

// FormatAsTimeseries formats Docker metrics as TimescaleDB-compatible timeseries data
func (dm *DockerMetrics) FormatAsTimeseries(host string) []TimeseriesPoint {
	points := make([]TimeseriesPoint, 0)
	
	baseTags := map[string]string{
		"host":   host,
		"type":   "gauge",
		"agent":  dm.AgentID,
	}
	
	// Add container counts
	points = append(points, TimeseriesPoint{
		Timestamp: dm.Timestamp,
		Metric:    "docker_running_containers",
		Value:     float64(dm.RunningContainers),
		Tags:      baseTags,
	})
	
	points = append(points, TimeseriesPoint{
		Timestamp: dm.Timestamp,
		Metric:    "docker_stopped_containers",
		Value:     float64(dm.StoppedContainers),
		Tags:      baseTags,
	})
	
	return points
}

// sanitizeContainerName creates a valid tag value from container name
func sanitizeContainerName(name string) string {
	cleaned := trimLeadingSlash(name)
	tag := ""
	
	for _, c := range cleaned {
		if c == '-' || c == '_' || c == '/' || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') {
			tag += string(c)
		}
	}
	
	if tag == "" {
		tag = "unnamed"
	}
	
	return tag
}

// trimLeadingSlash removes leading slash from strings
func trimLeadingSlash(s string) string {
	for len(s) > 0 && s[0] == '/' {
		s = s[1:]
	}
	return s
}
