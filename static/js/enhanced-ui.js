// Modern Notification System
class NotificationManager {
    constructor() {
        this.container = this.createContainer();
        this.notifications = new Map();
    }

    createContainer() {
        const container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
        return container;
    }

    show(message, type = 'info', duration = 5000) {
        const notification = this.createNotification(message, type);
        const id = Date.now().toString();
        
        this.notifications.set(id, notification);
        this.container.appendChild(notification);

        // Trigger animation
        requestAnimationFrame(() => {
            notification.style.opacity = '1';
            notification.style.transform = 'translateX(0)';
        });

        // Auto-dismiss
        if (duration > 0) {
            setTimeout(() => this.dismiss(id), duration);
        }

        return id;
    }

    createNotification(message, type) {
        const notification = document.createElement('div');
        notification.className = `toast ${type}`;
        notification.style.opacity = '0';
        notification.style.transform = 'translateX(100%)';
        notification.style.transition = 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)';

        const icon = this.getIcon(type);
        notification.innerHTML = `
            <i class="fas ${icon}"></i>
            <span>${message}</span>
            <button class="toast-close" onclick="window.notifications.dismiss('${Date.now()}')">
                <i class="fas fa-times"></i>
            </button>
        `;

        return notification;
    }

    getIcon(type) {
        const icons = {
            success: 'fa-check-circle',
            error: 'fa-exclamation-circle',
            warning: 'fa-exclamation-triangle',
            info: 'fa-info-circle'
        };
        return icons[type] || icons.info;
    }

    dismiss(id) {
        const notification = this.notifications.get(id);
        if (notification) {
            notification.style.opacity = '0';
            notification.style.transform = 'translateX(100%)';
            
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
                this.notifications.delete(id);
            }, 300);
        }
    }

    success(message, duration) {
        return this.show(message, 'success', duration);
    }

    error(message, duration) {
        return this.show(message, 'error', duration);
    }

    warning(message, duration) {
        return this.show(message, 'warning', duration);
    }

    info(message, duration) {
        return this.show(message, 'info', duration);
    }
}

// Enhanced Loading Manager
class LoadingManager {
    constructor() {
        this.overlay = this.createOverlay();
        this.activeLoaders = new Set();
    }

    createOverlay() {
        const overlay = document.createElement('div');
        overlay.className = 'loading-overlay';
        overlay.innerHTML = `
            <div class="loading-spinner">
                <div class="spinner"></div>
                <p>Загрузка...</p>
            </div>
        `;
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(4px);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 9999;
        `;
        document.body.appendChild(overlay);
        return overlay;
    }

    show(id = 'default', message = 'Загрузка...') {
        this.activeLoaders.add(id);
        this.overlay.querySelector('p').textContent = message;
        this.overlay.style.display = 'flex';
        this.overlay.style.opacity = '0';
        requestAnimationFrame(() => {
            this.overlay.style.transition = 'opacity 0.2s ease';
            this.overlay.style.opacity = '1';
        });
    }

    hide(id = 'default') {
        this.activeLoaders.delete(id);
        if (this.activeLoaders.size === 0) {
            this.overlay.style.opacity = '0';
            setTimeout(() => {
                this.overlay.style.display = 'none';
            }, 200);
        }
    }

    button(button, promise, originalText) {
        const loadingText = '<i class="fas fa-spinner fa-spin"></i> Загрузка...';
        button.innerHTML = loadingText;
        button.disabled = true;

        promise.finally(() => {
            button.innerHTML = originalText || button.getAttribute('data-original-text') || 'Готово';
            button.disabled = false;
        });
    }
}

// Enhanced Theme Manager
class ThemeManager {
    constructor() {
        this.currentTheme = this.getSystemTheme();
        this.init();
    }

    getSystemTheme() {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    init() {
        // Listen for system theme changes
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            this.currentTheme = e.matches ? 'dark' : 'light';
            this.applyTheme();
        });

        this.applyTheme();
    }

    applyTheme() {
        document.documentElement.setAttribute('data-theme', this.currentTheme);
        
        // Update meta theme-color for mobile browsers
        let themeColorMeta = document.querySelector('meta[name="theme-color"]');
        if (!themeColorMeta) {
            themeColorMeta = document.createElement('meta');
            themeColorMeta.name = 'theme-color';
            document.head.appendChild(themeColorMeta);
        }
        
        const themeColor = this.currentTheme === 'dark' ? '#141218' : '#FFFBFE';
        themeColorMeta.content = themeColor;
    }

    toggle() {
        this.currentTheme = this.currentTheme === 'dark' ? 'light' : 'dark';
        this.applyTheme();
        return this.currentTheme;
    }
}

// Status Monitor
class StatusMonitor {
    constructor() {
        this.updateInterval = 30000; // 30 seconds
        this.init();
    }

    init() {
        this.updateHostStatuses();
        setInterval(() => this.updateHostStatuses(), this.updateInterval);
    }

    updateHostStatuses() {
        const rows = document.querySelectorAll('#hosts-table-body tr');
        const now = new Date();

        rows.forEach(row => {
            const timeElement = row.querySelector('time');
            if (timeElement) {
                const lastSeenAttr = timeElement.getAttribute('datetime');
                if (lastSeenAttr) {
                    const lastSeen = new Date(lastSeenAttr);
                    const diffMinutes = (now - lastSeen) / (1000 * 60);

                    let status = 'online';
                    let statusText = 'Online';
                    
                    if (diffMinutes > 60) {
                        status = 'offline';
                        statusText = 'Offline';
                    } else if (diffMinutes > 30) {
                        status = 'warning';
                        statusText = 'Warning';
                    }

                    row.setAttribute('data-status', status);

                    const statusBadge = row.querySelector('.status-badge');
                    if (statusBadge) {
                        statusBadge.className = `status-badge status-${status}`;
                        statusBadge.textContent = statusText;
                    }

                    // Add status dot if not exists
                    let statusDot = row.querySelector('.status-dot');
                    if (!statusDot) {
                        statusDot = document.createElement('span');
                        statusDot.className = 'status-dot';
                        const macCell = row.querySelector('td:first-child .mac-address');
                        if (macCell) {
                            macCell.insertBefore(statusDot, macCell.firstChild);
                        }
                    }
                    statusDot.className = `status-dot ${status}`;
                }
            }
        });
    }
}

// Performance Monitor
class PerformanceMonitor {
    constructor() {
        this.metrics = {
            pageLoad: 0,
            apiCalls: new Map(),
            errors: []
        };
        this.init();
    }

    init() {
        // Monitor page load performance
        window.addEventListener('load', () => {
            const navigation = performance.getEntriesByType('navigation')[0];
            this.metrics.pageLoad = navigation.loadEventEnd - navigation.fetchStart;
            console.log(`Page loaded in ${this.metrics.pageLoad}ms`);
        });

        // Monitor errors
        window.addEventListener('error', (event) => {
            this.metrics.errors.push({
                message: event.message,
                filename: event.filename,
                line: event.lineno,
                timestamp: new Date()
            });
        });
    }

    measureApiCall(name, promise) {
        const start = performance.now();
        
        return promise.finally(() => {
            const duration = performance.now() - start;
            this.metrics.apiCalls.set(name, duration);
            console.log(`API call "${name}" took ${duration.toFixed(2)}ms`);
        });
    }

    getMetrics() {
        return {
            ...this.metrics,
            apiCalls: Object.fromEntries(this.metrics.apiCalls)
        };
    }
}

// Initialize global managers
window.notifications = new NotificationManager();
window.loading = new LoadingManager();
window.theme = new ThemeManager();
window.statusMonitor = new StatusMonitor();
window.performance = new PerformanceMonitor();

// Enhanced error handling
window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection:', event.reason);
    window.notifications.error('Произошла ошибка при выполнении операции');
});

// Add keyboard shortcuts
document.addEventListener('keydown', (event) => {
    // Ctrl/Cmd + K to focus search (if implemented)
    if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
        event.preventDefault();
        // Implement search focus
    }
    
    // ESC to close modals
    if (event.key === 'Escape') {
        const openModal = document.querySelector('.modal[style*="flex"]');
        if (openModal) {
            const closeBtn = openModal.querySelector('.close-modal');
            if (closeBtn) closeBtn.click();
        }
    }
});

// Add loading spinner styles
const spinnerStyles = `
.loading-spinner {
    text-align: center;
    color: white;
}

.spinner {
    width: 40px;
    height: 40px;
    border: 3px solid rgba(255, 255, 255, 0.3);
    border-top: 3px solid white;
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin: 0 auto 16px;
}

.toast-close {
    background: none;
    border: none;
    color: var(--on-surface-variant);
    cursor: pointer;
    padding: 4px;
    border-radius: var(--radius-sm);
    transition: all 0.2s ease;
    margin-left: auto;
}

.toast-close:hover {
    background: var(--surface-variant);
    color: var(--on-surface);
}
`;

const styleSheet = document.createElement('style');
styleSheet.textContent = spinnerStyles;
document.head.appendChild(styleSheet);

console.log('Enhanced UI system initialized ✨');