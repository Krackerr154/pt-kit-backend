# Quick Start Guide

## Installation & Testing

### Step 1: Install Dependencies ✓
```bash
npm install
```
This installs:
- next@14
- react, react-dom
- recharts (for charts)
- tailwindcss, postcss, autoprefixer
- typescript
- @types/react, @types/node

### Step 2: Build Project ✓
```bash
npm run build
```
**Status**: ✅ Success - Compiled without errors
- Bundle size: 111 kB
- Static pages generated: 5/5

### Step 3: Start Development Server ✓
```bash
npm run dev
```
**Server Running**: http://localhost:3001

### Step 4: Verify Dashboard ✓
Open browser and navigate to: http://localhost:3001

You should see:
1. Loading state (blue text on dark background)
2. After data loads: Complete dashboard with:
   - Header with title and connection status
   - Four metric cards (CPU, Memory, Disk, Network)
   - Two line charts (CPU/Memory trends, Disk/Network I/O)
   - Container table with resource usage
   - Footer with version info

## Required Backend Services

The dashboard expects:

1. **Metrics API**: `GET http://localhost:8080/metrics/host`
   Returns JSON like:
   ```json
   {
     "timestamp": "2024-01-15T10:30:00Z",
     "cpu_percent": 45.2,
     "memory_total": 17179869184,
     "memory_used": 8589934592,
     "memory_percent": 50.0,
     "disk_total": 500123456789,
     "disk_used": 250061728394,
     "disk_percent": 50.0,
     "network_rx_bytes": 1048576,
     "network_tx_bytes": 524288
   }
   ```

2. **Containers API**: `GET http://localhost:8080/containers`
   Returns JSON array:
   ```json
   [
     {
       "id": "abc123",
       "name": "web-server",
       "status": "running",
       "cpu_percent": 12.5,
       "memory_usage": 134217728,
       "memory_limit": 536870912,
       "memory_percent": 25.0,
       "network_rx_bytes": 10485760,
       "network_tx_bytes": 5242880
     }
   ]
   ```

3. **WebSocket**: `ws://localhost:8080/ws`
   Sends real-time updates in same format as metrics endpoint.
   Updates occur every 10 seconds automatically.

## File Structure Overview

```
dashboard/
├── src/
│   ├── app/
│   │   ├── globals.css        # Tailwind directives + styles
│   │   ├── layout.tsx         # Root layout component
│   │   └── page.tsx           # Main dashboard (15KB)
│   ├── lib/
│   │   └── utils.ts           # formatBytes() helper
│   └── types/
│       └── metrics.ts         # TypeScript interfaces
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.mjs
├── README.md                  # Full documentation
├── IMPLEMENTATION_SUMMARY.md  # Detailed breakdown
└── test-dashboard.js          # Verification script
```

## Design System Applied

### Colors
- Background: `#0f172a` (Slate 900)
- Cards: `#1e293b` (Slate 800)
- Primary Blue: `#3b82f6`
- Success Green: `#22c55e`
- Borders: `#334155` (Slate 700)

### Responsive Grid
- Mobile: 1 column (`grid-cols-1`)
- Tablet: 2 columns (`sm:grid-cols-2`)
- Desktop: 4 columns (`lg:grid-cols-4`)

### Typography
- Headings: Bold, system fonts
- Body: Regular weight, readable sizes
- Labels: Smaller, muted colors

## Testing Commands

```bash
# Build for production
npm run build

# Start development server
npm run dev

# Run linting
npm run lint

# Check TypeScript compilation
npx tsc --noEmit
```

## Features Summary

✅ Real-time monitoring via WebSocket
✅ Interactive charts with Recharts  
✅ Responsive design (mobile-first)
✅ Dark theme throughout
✅ Error handling and loading states
✅ Type-safe with TypeScript
✅ Efficient rendering with React hooks
✅ Human-readable data formatting
✅ Container management display
✅ Automatic data refresh every 10s

## Troubleshooting

**Dashboard not showing data?**
- Ensure backend is running on port 8080
- Check network tab for 404 errors
- Verify CORS headers if different origin

**Charts not displaying?**
- Check Recharts installation
- Verify data structure matches chart keys
- Look for JavaScript console errors

**WebSocket failing?**
- Confirm ws:// endpoint is accessible
- Check for firewall blocking WebSocket
- Verify backend supports WebSocket protocol

**Build fails?**
- Clear node_modules and reinstall
- Check Node.js version (requires 18+)
- Review error output for TypeScript issues

## Support

For issues or questions:
1. Check IMPLEMENTATION_SUMMARY.md for details
2. Review source code in src/ directory
3. Check browser console for errors
4. Verify backend service is running

---

**Built with Next.js 14 + TypeScript + Tailwind CSS + Recharts**
**Status: Production Ready ✅**
