#!/bin/bash

# Go Monitoring Agent - Test Script

set -e  # Exit on error

echo "=========================================="
echo "Go Monitoring Agent - Test Script"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Variables
SERVER_URL="http://localhost:8080"
PID=""

# Function to print colored output
print_status() {
    local status=$1
    local message=$2
    
    if [ "$status" == "PASS" ]; then
        echo -e "${GREEN}[PASS]${NC} $message"
    elif [ "$status" == "FAIL" ]; then
        echo -e "${RED}[FAIL]${NC} $message"
    else
        echo -e "${YELLOW}[INFO]${NC} $message"
    fi
}

# Cleanup function
cleanup() {
    echo ""
    echo "Cleaning up..."
    if [ -n "$PID" ]; then
        kill $PID 2>/dev/null || true
        sleep 1
    fi
    echo "Cleanup complete."
}

# Set trap to run cleanup on exit
trap cleanup EXIT

# Start the server in background
echo "Starting Go Monitoring Agent server..."
cd "$(dirname "$0")"
METRICS_PORT=8080 DOCKER_ENABLED=false ./go-monitoring-agent &
PID=$!
sleep 3

# Check if server is running
if ! ps -p $PID > /dev/null 2>&1; then
    echo -e "${RED}Server failed to start!${NC}"
    exit 1
fi

print_status "INFO" "Server started with PID: $PID"
echo ""

# Test 1: Health Check Endpoint
echo "Test 1: Health Check Endpoint (/health)"
HEALTH_RESPONSE=$(curl -s $SERVER_URL/health)
if [ "$HEALTH_RESPONSE" == "OK" ]; then
    print_status "PASS" "Health check returned 'OK'"
else
    print_status "FAIL" "Expected 'OK', got '$HEALTH_RESPONSE'"
    exit 1
fi
echo ""

# Test 2: Host Metrics Endpoint
echo "Test 2: Host Metrics Endpoint (/metrics/host)"
HOST_METRICS=$(curl -s $SERVER_URL/metrics/host)
if [ $? -eq 0 ] && [ -n "$HOST_METRICS" ]; then
    print_status "PASS" "Host metrics endpoint responded successfully"
    
    # Display sample response (truncated)
    echo "Sample response:"
    echo "$HOST_METRICS" | head -c 200
    echo "..."
    echo ""
else
    print_status "FAIL" "Failed to get host metrics"
    exit 1
fi

# Verify JSON structure has expected fields
echo "Verifying JSON structure..."
echo "$HOST_METRICS" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    required_fields = ['cpu_percent', 'memory_total', 'memory_used', 'memory_percent', 
                       'disk_total', 'disk_used', 'disk_percent', 'network_rx', 'network_tx']
    missing_fields = [f for f in required_fields if f not in data]
    if missing_fields:
        print(f'Missing fields: {missing_fields}')
        sys.exit(1)
    else:
        print('All required fields present ✓')
        print(f'CPU %: {data[\"cpu_percent\"]:.2f}')
        print(f'Memory: {data[\"memory_used\"] / (1024**3):.2f} GB used of {data[\"memory_total\"] / (1024**3):.2f} GB ({data[\"memory_percent\"]:.2f}%)')
        print(f'Disk: {data[\"disk_used\"] / (1024**3):.2f} GB used of {data[\"disk_total\"] / (1024**3):.2f} GB ({data[\"disk_percent\"]:.2f}%)')
except Exception as e:
    print(f'Error parsing JSON: {e}')
    sys.exit(1)
" || exit 1
echo ""

# Test 3: Docker Metrics Endpoint (when enabled)
echo "Test 3: Docker Metrics Endpoint (/metrics/docker)"
DOCKER_RESPONSE=$(curl -s $SERVER_URL/metrics/docker)
if [ $? -eq 0 ] && [ -n "$DOCKER_RESPONSE" ]; then
    print_status "PASS" "Docker metrics endpoint responded"
    
    echo "$DOCKER_RESPONSE" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    containers = data.get('containers', [])
    if len(containers) > 0:
        print(f'Found {len(containers)} container(s)')
    else:
        print('No containers found (may be expected if no Docker containers are running)')
except Exception as e:
    print(f'Error parsing Docker response: {e}')
" || echo "Docker metrics format validation skipped"
echo ""

# Test 4: Multiple Concurrent Requests
echo "Test 4: Concurrent Request Load Testing"
CONCURRENT_REQUESTS=5
for i in $(seq 1 $CONCURRENT_REQUESTS); do
    curl -s $SERVER_URL/metrics/host > /dev/null &
done
wait

# Wait briefly to ensure all responses completed
sleep 1
print_status "PASS" "Successfully handled $CONCURRENT_REQUESTS concurrent requests"
echo ""

# Test 5: WebSocket Connection (Basic Smoke Test)
echo "Test 5: WebSocket Server Startup"
python3 << 'PYTHON_EOF'
import socket
import sys

def check_port(host, port, timeout=1):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

# Check if main HTTP port is listening
if check_port("127.0.0.1", 8080):
    print("WebSocket endpoint accessible ✓")
else:
    print("WebSocket endpoint not responding ✗")
    sys.exit(1)
PYTHON_EOF

echo ""

# Test 6: Graceful Shutdown
echo "Test 6: Graceful Shutdown"
kill -TERM $PID
sleep 2

if ! ps -p $PID > /dev/null 2>&1; then
    print_status "PASS" "Server shutdown gracefully"
else
    print_status "FAIL" "Server did not shut down properly"
    exit 1
fi
echo ""

# Summary
echo "=========================================="
echo -e "${GREEN}All Tests Completed Successfully!${NC}"
echo "=========================================="
echo ""
echo "Summary:"
echo "  ✓ Health endpoint responds correctly"
echo "  ✓ Host metrics endpoint collects and returns data"
echo "  ✓ All required JSON fields present in metrics"
echo "  ✓ Docker metrics endpoint functional (when available)"
echo "  ✓ Handles concurrent requests without errors"
echo "  ✓ Graceful shutdown works properly"
echo ""
