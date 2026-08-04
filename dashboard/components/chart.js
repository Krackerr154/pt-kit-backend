/**
 * Lunar Sintering Simulator - Chart Component
 * Renders telemetry data on HTML5 Canvas with auto-scaling and smooth animations
 */

class ChartComponent {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        
        // Chart configuration
        this.config = {
            lineColor: '#4fc3f7',
            bulkTempColor: '#ffb74d',
            gridColor: 'rgba(255, 255, 255, 0.1)',
            textColor: '#b0b3d1',
            lineWidth: 2,
            pointRadius: 3,
            animationDuration: 500,
            maxDataPoints: 300
        };
        
        // Data storage
        this.surfaceTempData = [];
        this.bulkTempData = [];
        this.maxTime = 0;
        
        // Animation state
        this.lastFrameTime = 0;
        this.animationProgress = 0;
        this.isAnimating = false;
        
        // Initialize chart
        this.init();
    }
    
    init() {
        this.setupCanvas();
        this.render();
        console.log('Chart component initialized');
    }
    
    setupCanvas() {
        if (!this.canvas) {
            throw new Error(`Canvas with id '${this.canvasId}' not found`);
        }
        
        // Get CSS dimensions and set actual canvas size
        const rect = this.canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        
        this.ctx.scale(dpr, dpr);
        
        this.chartWidth = rect.width;
        this.chartHeight = rect.height;
        
        // Add resize listener
        window.addEventListener('resize', () => {
            this.handleResize();
        });
    }
    
    handleResize() {
        const rect = this.canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        
        this.ctx.scale(dpr, dpr);
        
        this.chartWidth = rect.width;
        this.chartHeight = rect.height;
        
        this.render();
    }
    
    /**
     * Add a new data point to the chart
     * @param {Object} data - Object containing time, surfaceTemp, and bulkTemp values
     */
    addPoint(data) {
        const { time, surfaceTemp, bulkTemp } = data;
        
        this.surfaceTempData.push({ time, value: surfaceTemp });
        this.bulkTempData.push({ time, value: bulkTemp });
        
        // Keep only recent data points
        if (this.surfaceTempData.length > this.config.maxDataPoints) {
            this.surfaceTempData.shift();
            this.bulkTempData.shift();
        }
        
        // Update max time for scaling
        if (time > this.maxTime) {
            this.maxTime = time;
        }
        
        // Trigger frame update
        this.isAnimating = true;
    }
    
    /**
     * Clear all data from the chart
     */
    clear() {
        this.surfaceTempData = [];
        this.bulkTempData = [];
        this.maxTime = 0;
        this.render();
    }
    
    /**
     * Calculate Y-axis range based on data values
     * Returns { min, max, padding } for both temperature scales
     */
    calculateYAxisRange() {
        let minVal = Infinity;
        let maxVal = -Infinity;
        
        // Include both temperature series in calculation
        const allValues = [
            ...this.surfaceTempData.map(d => d.value),
            ...this.bulkTempData.map(d => d.value)
        ];
        
        if (allValues.length === 0) {
            return { min: 0, max: 100, padding: 10 };
        }
        
        minVal = Math.min(...allValues);
        maxVal = Math.max(...allValues);
        
        // Add padding to prevent lines touching edges
        const range = maxVal - minVal;
        const padding = range * 0.1 || 10;
        
        return {
            min: minVal - padding,
            max: maxVal + padding,
            padding
        };
    }
    
    /**
     * Convert data coordinates to canvas coordinates
     */
    toCanvasX(time) {
        const dataWidth = this.chartWidth - 80; // Leave space for labels
        const padding = 60;
        
        if (this.maxTime <= 0) {
            return padding;
        }
        
        const normalizedTime = time / this.maxTime;
        return padding + normalizedTime * dataWidth;
    }
    
    toCanvasY(value, yAxisRange) {
        const chartHeight = this.chartHeight - 40; // Leave space for labels
        const padding = 40;
        
        const normalizedValue = (value - yAxisRange.min) / 
                               (yAxisRange.max - yAxisRange.min);
        
        return (chartHeight - padding) - normalizedValue * (chartHeight - 2 * padding);
    }
    
    /**
     * Draw the grid lines
     */
    drawGrid(yAxisRange) {
        const ctx = this.ctx;
        const chartHeight = this.chartHeight - 40;
        const padding = 40;
        const width = this.chartWidth - 80;
        const height = chartHeight - 2 * padding;
        
        // Horizontal grid lines
        ctx.strokeStyle = this.config.gridColor;
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        
        // Draw 5 horizontal grid lines
        const gridLines = 5;
        for (let i = 0; i <= gridLines; i++) {
            const y = padding + (i / gridLines) * height;
            ctx.moveTo(60, y);
            ctx.lineTo(this.chartWidth, y);
            
            // Draw Y-axis label
            const value = yAxisRange.max - (i / gridLines) * (yAxisRange.max - yAxisRange.min);
            ctx.fillStyle = this.config.textColor;
            ctx.font = '11px Segoe UI';
            ctx.textAlign = 'right';
            ctx.fillText(Math.round(value).toString(), 55, y + 4);
        }
        
        ctx.stroke();
    }
    
    /**
     * Draw a single data series as a line
     */
    drawSeries(data, color, xConverter, yConverter) {
        const ctx = this.ctx;
        const padding = 60;
        const chartHeight = this.chartHeight - 40;
        const height = chartHeight - 80;
        
        if (data.length < 2) return;
        
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = this.config.lineWidth;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        
        const firstPoint = data[0];
        ctx.moveTo(xConverter(firstPoint.time), yConverter(firstPoint.value));
        
        for (let i = 1; i < data.length; i++) {
            const point = data[i];
            const x = xConverter(point.time);
            const y = yConverter(point.value);
            ctx.lineTo(x, y);
        }
        
        ctx.stroke();
        
        // Draw gradient fill under the line
        ctx.closePath();
        const gradient = ctx.createLinearGradient(0, padding, 0, chartHeight);
        gradient.addColorStop(0, this.alphaColor(color, 0.3));
        gradient.addColorStop(1, this.alphaColor(color, 0.02));
        
        ctx.fillStyle = gradient;
        ctx.fill();
        
        // Draw points at regular intervals
        const pointSpacing = Math.ceil(data.length / 20);
        for (let i = 0; i < data.length; i += pointSpacing) {
            const point = data[i];
            const x = xConverter(point.time);
            const y = yConverter(point.value);
            
            ctx.beginPath();
            ctx.arc(x, y, this.config.pointRadius, 0, Math.PI * 2);
            ctx.fillStyle = color;
            ctx.fill();
        }
    }
    
    /**
     * Make a color transparent
     */
    alphaColor(hex, alpha) {
        if (hex.startsWith('#')) {
            hex = hex.slice(1);
        }
        
        const r = parseInt(hex.slice(0, 2), 16);
        const g = parseInt(hex.slice(2, 4), 16);
        const b = parseInt(hex.slice(4, 6), 16);
        
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
    
    /**
     * Draw X-axis labels
     */
    drawXAxis() {
        const ctx = this.ctx;
        const padding = 60;
        const width = this.chartWidth - 80;
        
        ctx.fillStyle = this.config.textColor;
        ctx.font = '11px Segoe UI';
        ctx.textAlign = 'center';
        
        const numLabels = 6;
        for (let i = 0; i <= numLabels; i++) {
            const time = (i / numLabels) * this.maxTime;
            const x = padding + (i / numLabels) * width;
            ctx.fillText(time.toFixed(0) + 's', x, this.chartHeight - 15);
        }
    }
    
    /**
     * Main render method - draws the complete chart
     */
    render() {
        if (!this.ctx) return;
        
        // Clear canvas
        this.ctx.clearRect(0, 0, this.chartWidth, this.chartHeight);
        
        if (this.surfaceTempData.length === 0 && this.bulkTempData.length === 0) {
            // Show placeholder text
            this.ctx.fillStyle = '#7b7f9a';
            this.ctx.font = '14px Segoe UI';
            this.ctx.textAlign = 'center';
            this.ctx.fillText('No data available', this.chartWidth / 2, this.chartHeight / 2);
            return;
        }
        
        // Calculate Y-axis range
        const yAxisRange = this.calculateYAxisRange();
        
        // Draw grid
        this.drawGrid(yAxisRange);
        
        // Draw data series
        this.drawSeries(
            this.surfaceTempData, 
            this.config.lineColor,
            (t) => this.toCanvasX(t),
            (v) => this.toCanvasY(v, yAxisRange)
        );
        
        this.drawSeries(
            this.bulkTempData,
            this.config.bulkTempColor,
            (t) => this.toCanvasX(t),
            (v) => this.toCanvasY(v, yAxisRange)
        );
        
        // Draw X-axis labels
        this.drawXAxis();
        
        this.isAnimating = false;
    }
    
    /**
     * Start animation loop for smooth transitions
     */
    startAnimation() {
        const animate = (timestamp) => {
            if (!this.lastFrameTime) {
                this.lastFrameTime = timestamp;
            }
            
            const deltaTime = timestamp - this.lastFrameTime;
            
            if (deltaTime >= 16) { // ~60fps
                this.render();
                this.lastFrameTime = timestamp;
            }
            
            if (this.isAnimating) {
                requestAnimationFrame(animate);
            }
        };
        
        requestAnimationFrame(animate);
    }
}

// Export for module systems (if available)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ChartComponent;
}
