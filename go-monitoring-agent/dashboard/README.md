# System Monitoring Dashboard

A real-time Next.js 14 dashboard for monitoring system metrics with WebSocket live updates.

## Features

- **Real-time Metrics Display**: Live CPU, Memory, Disk, and Network monitoring
- **Interactive Charts**: Two Recharts line charts showing trends over time
- **Container Management Table**: View running containers with resource usage
- **WebSocket Integration**: Real-time data streaming via WebSocket
- **Responsive Design**: Mobile-first Tailwind CSS grid layout
- **Dark Theme**: Modern slate-based color scheme (#0f172a background, #1e293b cards)

## Tech Stack

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **Charts**: Recharts
- **Real-time**: WebSocket API

## Getting Started

### Prerequisites

- Node.js 18+ 
- npm or yarn

### Installation

1. Install dependencies:
```bash
npm install
```

2. Start the development server:
```bash
npm run dev
```

The dashboard will be available at `http://localhost:3001`

## Project Structure

```
dashboard/
├── src/
│   ├── app/
│   │   ├── globals.css      # Global styles with Tailwind directives
│   │   ├── layout.tsx       # Root layout component
│   │   └── page.tsx         # Main dashboard page
│   ├── lib/
│   │   └── utils.ts         # Utility functions (formatBytes, formatNumber)
│   └── types/
│       └── metrics.ts       # TypeScript type definitions
├── public/                  # Static assets
├── package.json             # Dependencies and scripts
├── tailwind.config.ts       # Tailwind configuration
└── tsconfig.json            # TypeScript configuration
```

## API Endpoints

The dashboard expects data from:

- **Metrics Endpoint**: `GET http://localhost:8080/metrics/host`
- **Containers Endpoint**: `GET http://localhost:8080/containers`
- **WebSocket**: `ws://localhost:8080/ws`

## Data Flow

1. On mount, fetch initial host metrics from `/metrics/host`
2. Establish WebSocket connection to `ws://localhost:8080/ws`
3. Receive real-time updates every 10 seconds
4. Store last 50 data points in history array for chart visualization
5. Update UI components reactively using React hooks

## Components

### DashboardPage
Main container component that manages:
- State for host metrics, containers, and history
- WebSocket connection lifecycle
- Data fetching and error handling
- Responsive layout rendering

### Metric Cards
Four cards displaying current system metrics:
- CPU Usage (%)
- Memory Usage (% + bytes)
- Disk Usage (% + bytes)
- Network Traffic (RX/TX in bytes)

### Chart Section
Two interactive charts using Recharts:
- **CPU & Memory Chart**: Line chart showing usage percentages over time
- **Disk & Network Chart**: Line chart showing disk used and network traffic

### Container Table
Table view of running containers with columns:
- Name
- Status (running/stopped)
- CPU %
- Memory usage & percentage
- Network RX/TX bytes

### Footer
Displays version information and last update timestamp.

## Color Scheme

- **Background**: #0f172a (Slate 900)
- **Cards**: #1e293a (Slate 800)
- **Primary Blue**: #3b82f6
- **Success Green**: #22c55e
- **Text Gray**: Various shades from Slate palette

## Responsive Breakpoints

- **Mobile**: Single column layout (< 640px)
- **Tablet**: Two column grid (640px - 1024px)
- **Desktop**: Four column grid (> 1024px)

## Development

### Build Production Bundle
```bash
npm run build
```

### Start Production Server
```bash
npm run start
```

### Lint Code
```bash
npm run lint
```

## Future Enhancements

- [ ] Add refresh button for manual data reload
- [ ] Implement date range filtering for charts
- [ ] Add alert thresholds for metrics
- [ ] Support multiple hosts
- [ ] Export metrics as CSV/PDF
- [ ] Add authentication layer

## License

MIT License
