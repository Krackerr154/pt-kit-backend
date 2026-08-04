FROM golang:1.19-alpine AS builder

WORKDIR /app

# Install dependencies
RUN apk add --no-cache git gcc musl-dev make

# Copy go mod files
COPY go.mod .
RUN go mod download

# Copy source code
COPY main.go .
COPY websocket.go .

# Build binary
RUN CGO_ENABLED=0 GOOS=linux go build -a -o go-monitoring-agent .

# Final stage
FROM alpine:latest

RUN apk --no-cache add ca-certificates tzdata

WORKDIR /root/

# Copy binary from builder
COPY --from=builder /app/go-monitoring-agent .

EXPOSE 8080

ENV METRICS_PORT=8080
ENV DOCKER_ENABLED=false

CMD ["./go-monitoring-agent"]
