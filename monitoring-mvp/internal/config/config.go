package config

import (
	"os"
	"time"
)

// Config holds application configuration
type Config struct {
	Name             string        `env:"AGENT_NAME"`
	LogLevel         string        `env:"LOG_LEVEL"`
	CollectionInterval time.Duration `env:"COLLECTION_INTERVAL"`
	DatabaseURL      string        `env:"DATABASE_URL"`
	APIServerPort    int           `env:"API_PORT"`
	MetricsEnabled   bool          `env:"METRICS_ENABLED"`
	MetricsPort      int           `env:"METRICS_PORT"`
	MaxCollectors    int           `env:"MAX_CONCURRENT_COLLECTORS"`
	BufferSize       int           `env:"BUFFER_SIZE"`
}

// DefaultConfig returns a configuration with sensible defaults
func DefaultConfig() *Config {
	return &Config{
		Name:             "monitoring-agent",
		LogLevel:         "info",
		CollectionInterval: 10 * time.Second,
		APIServerPort:    8080,
		MetricsEnabled:   true,
		MetricsPort:      9091,
		MaxCollectors:    4,
		BufferSize:       1000,
	}
}

// Load loads configuration from environment variables
func Load() (*Config, error) {
	cfg := DefaultConfig()
	
	if name := os.Getenv("AGENT_NAME"); name != "" {
		cfg.Name = name
	}
	if logLevel := os.Getenv("LOG_LEVEL"); logLevel != "" {
		cfg.LogLevel = logLevel
	}
	if interval := os.Getenv("COLLECTION_INTERVAL"); interval != "" {
		duration, err := time.ParseDuration(interval)
		if err == nil {
			cfg.CollectionInterval = duration
		}
	}
	if dbURL := os.Getenv("DATABASE_URL"); dbURL != "" {
		cfg.DatabaseURL = dbURL
	}
	
	return cfg, nil
}
