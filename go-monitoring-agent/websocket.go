package main

import (
	"encoding/json"
	"log"
	"net/http"

	"github.com/gorilla/websocket"
)

var (
	metricsChan = make(chan *HostMetrics, 10) // Channel for metrics updates
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	CheckOrigin: func(r *http.Request) bool {
		return true // Allow all origins for development
	},
}

// wsHandler handles WebSocket connections for real-time metrics streaming
func wsHandler(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket upgrade error: %v", err)
		return
	}
	defer conn.Close()

	for {
		// Read message from client
		_, _, err := conn.ReadMessage()
		if err != nil {
			break
		}
		
		// Send back latest metrics
		updateWSMetrics(conn)
	}
}

// broadcastMetrics sends metrics to all connected WebSocket clients
func broadcastMetrics(metrics *HostMetrics) {
	select {
	case metricsChan <- metrics:
		// Metrics added to queue
	default:
		// Queue is full, skip this metric
	}
}

// updateWSMetrics sends metrics to a specific WebSocket client
func updateWSMetrics(conn *websocket.Conn) {
	currentMetrics := getLastMetrics()
	
	data, err := json.Marshal(currentMetrics)
	if err != nil {
		log.Printf("Error encoding metrics: %v", err)
		return
	}

	err = conn.WriteMessage(websocket.TextMessage, data)
	if err != nil {
		log.Printf("Error writing WebSocket message: %v", err)
		conn.Close()
		return
	}
}

// GetLastMetrics retrieves the last stored metrics
func getLastMetrics() *HostMetrics {
	metricsMutex.RLock()
	defer metricsMutex.RUnlock()
	
	if lastMetrics == nil {
		return &HostMetrics{}
	}
	return lastMetrics
}
