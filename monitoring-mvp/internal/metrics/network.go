package metrics

import (
	"fmt"
	"time"

	"github.com/shirou/gopsutil/v3/net"
)

// NetworkStats holds network interface metrics
type NetworkStats struct {
	Timestamp      time.Time               `json:"timestamp"`
	AgentID        string                  `json:"agent_id"`
	TotalBytesSent uint64                  `json:"total_bytes_sent"`
	TotalBytesRecv uint64                  `json:"total_bytes_recv"`
	Interfaces     []NetworkInterfaceStats `json:"interfaces"`
}

// NetworkInterfaceStats holds network metrics for a single interface
type NetworkInterfaceStats struct {
	Name        string `json:"name"`
	IsUp        bool   `json:"is_up"`
	MACAddress  string `json:"mac_address,omitempty"`
	RxBytes     uint64 `json:"rx_bytes"`
	RxPackets   uint64 `json:"rx_packets"`
	RxErrors    uint64 `json:"rx_errors"`
	RxDropped   uint64 `json:"rx_dropped"`
	TxBytes     uint64 `json:"tx_bytes"`
	TxPackets   uint64 `json:"tx_packets"`
	TxErrors    uint64 `json:"tx_errors"`
	TxDropped   uint64 `json:"tx_dropped"`
}

// CollectNetwork collects network metrics from all interfaces
func CollectNetwork(agentID string) (*NetworkStats, error) {
	stats := &NetworkStats{
		Timestamp: time.Now(),
		AgentID:   agentID,
		Interfaces: make([]NetworkInterfaceStats, 0),
	}
	
	// Get IO counters for all interfaces
	ioCounters, err := net.IOCounters(true)
	if err != nil {
		return nil, fmt.Errorf("failed to get IO counters: %w", err)
	}
	
	for _, counter := range ioCounters {
		netIf := NetworkInterfaceStats{
			Name:      counter.Name,
			RxBytes:   counter.BytesRecv,
			RxPackets: counter.PacketsRecv,
			RxErrors:  counter.Errin,
			RxDropped: counter.Dropin,
			TxBytes:   counter.BytesSent,
			TxPackets: counter.PacketsSent,
			TxErrors:  counter.Errout,
			TxDropped: counter.Dropout,
		}
		
		// Try to get interface details (up/down status)
		interfaces, _ := net.Interfaces()
		for _, iface := range interfaces {
			if iface.Name == counter.Name {
				netIf.IsUp = isInterfaceUp(iface.Flags)
				netIf.MACAddress = iface.HardwareAddr
				break
			}
		}
		
		// Add to total
		stats.TotalBytesSent += counter.BytesSent
		stats.TotalBytesRecv += counter.BytesRecv
		
		stats.Interfaces = append(stats.Interfaces, netIf)
	}
	
	return stats, nil
}

// isInterfaceUp checks if an interface is up based on flags
func isInterfaceUp(flags uint32) bool {
	upFlag := uint32(1) // LinkUp
	return (flags & upFlag) != 0
}
