// Test file to verify dashboard structure and rendering
// Run with: npm run build (already passed in previous steps)

const expectedElements = {
  header: true,
  metricsCards: 4, // CPU, Memory, Disk, Network
  charts: 2, // CPU/Memory chart, Disk/Network chart
  containerTable: true,
  footer: true,
};

// Verify the page.tsx contains all required elements
const fs = require('fs');
const path = require('path');

const pagePath = path.join(__dirname, 'src/app/page.tsx');
const pageContent = fs.readFileSync(pagePath, 'utf8');

console.log('=== Dashboard Structure Verification ===\n');

// Check for key components
const checks = [
  { name: 'Header with title', pattern: /Dashboard|System Monitoring/i },
  { name: 'Connection status indicator', pattern: /isConnected|connection/i },
  { name: 'CPU Metrics Card', pattern: /cpu_percent.*card/i },
  { name: 'Memory Metrics Card', pattern: /memory_percent.*card/i },
  { name: 'Disk Metrics Card', pattern: /disk_percent.*card/i },
  { name: 'Network Metrics Card', pattern: /network.*metric/i },
  { name: 'CPU/Memory Line Chart', pattern: /LineChart.*cpu_percent.*memory_percent/i },
  { name: 'Disk/Network Line Chart', pattern: /LineChart.*disk_used.*network_rx/i },
  { name: 'Container Table', pattern: /container.*table/i },
  { name: 'Footer section', pattern: /footer|version/i },
  { name: 'formatBytes helper', pattern: /function formatBytes/i },
  { name: 'WebSocket connection', pattern: /new WebSocket.*ws:\/\/localhost:8080/i },
  { name: 'History array (50 points)', pattern: /\.slice\(.*-50/i },
];

let passed = 0;
let failed = 0;

checks.forEach(check => {
  const result = check.pattern.test(pageContent);
  if (result) {
    console.log(`✅ ${check.name}`);
    passed++;
  } else {
    console.log(`❌ ${check.name}`);
    failed++;
  }
});

console.log(`\n=== Results ===`);
console.log(`Passed: ${passed}/${checks.length}`);
console.log(`Failed: ${failed}/${checks.length}`);

if (failed === 0) {
  console.log('\n🎉 All dashboard elements verified successfully!');
  process.exit(0);
} else {
  console.log('\n⚠️ Some elements are missing.');
  process.exit(1);
}
