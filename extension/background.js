const DEFAULT_SERVER_URL = 'wss://localhost:52314';
const RECONNECT_DELAY = 5000;

let socket = null;
let isEnabled = false;
let currentAccount = '';
let serverUrl = DEFAULT_SERVER_URL;
let reconnectTimeout = null;

class CookieSyncClient {
    constructor() {
        this.requestId = 0;
        this.pendingRequests = new Map();
    }

    generateUuid() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    async register(account) {
        return this.sendCommand('register', account, {});
    }

    async sendCommand(command, account, payload) {
        return new Promise((resolve, reject) => {
            if (!socket || socket.readyState !== WebSocket.OPEN) {
                reject(new Error('Socket not connected'));
                return;
            }

            const uuid = this.generateUuid();
            const message = {
                command,
                account,
                uuid,
                payload
            };

            this.pendingRequests.set(uuid, {
                resolve,
                reject,
                timeout: setTimeout(() => {
                    this.pendingRequests.delete(uuid);
                    reject(new Error('Request timeout'));
                }, 10000)
            });

            try {
                socket.send(JSON.stringify(message));
            } catch (e) {
                this.pendingRequests.delete(uuid);
                reject(e);
            }
        });
    }

    handleMessage(data) {
        try {
            const response = JSON.parse(data);
            const { uuid, result, payload, command, message } = response;

            if (command === 'set') {
                this.handleSetCookies(payload);
                return;
            }

            if (uuid && this.pendingRequests.has(uuid)) {
                const { resolve, reject, timeout } = this.pendingRequests.get(uuid);
                clearTimeout(timeout);
                this.pendingRequests.delete(uuid);

                if (result) {
                    resolve(payload);
                    this.handleSetCookies(payload);
                } else {
                    reject(new Error(message || 'Request failed'));
                }
            }
        } catch (e) {
            console.error('Error parsing message:', e);
        }
    }

    handleSetCookies(payload) {
        if (!payload || typeof payload !== 'object') {
            return;
        }

        Object.entries(payload).forEach(([name, value]) => {
            chrome.cookies.set({
                url: 'http://localhost',
                name,
                value: String(value),
                expirationDate: Math.floor(Date.now() / 1000) + 86400 * 365
            });
        });

        chrome.runtime.sendMessage({
            type: 'statusUpdate'
        }).catch(() => {});
    }
}

const client = new CookieSyncClient();

function connect() {
    if (socket && socket.readyState === WebSocket.OPEN) {
        return;
    }

    console.log('[CookieSync] Connecting to:', serverUrl);

    try {
        socket = new WebSocket(serverUrl);

        socket.addEventListener('open', async () => {
            console.log('[CookieSync] Connected');
            clearTimeout(reconnectTimeout);

            if (currentAccount) {
                try {
                    await client.register(currentAccount);
                    console.log('[CookieSync] Registered as:', currentAccount);
                } catch (e) {
                    console.error('[CookieSync] Registration failed:', e);
                }
            }

            notifyStatusUpdate();
        });

        socket.addEventListener('message', (event) => {
            console.log('[CookieSync] Received:', event.data);
            client.handleMessage(event.data);
        });

        socket.addEventListener('close', () => {
            console.log('[CookieSync] Disconnected');
            notifyStatusUpdate();
            if (isEnabled) {
                scheduleReconnect();
            }
        });

        socket.addEventListener('error', (error) => {
            console.error('[CookieSync] Socket error:', error);
            notifyStatusUpdate();
        });
    } catch (e) {
        console.error('[CookieSync] Connection error:', e);
        if (isEnabled) {
            scheduleReconnect();
        }
    }
}

function disconnect() {
    clearTimeout(reconnectTimeout);
    if (socket) {
        socket.close();
        socket = null;
    }
}

function scheduleReconnect() {
    if (reconnectTimeout) {
        return;
    }
    reconnectTimeout = setTimeout(() => {
        reconnectTimeout = null;
        if (isEnabled) {
            connect();
        }
    }, RECONNECT_DELAY);
}

function notifyStatusUpdate() {
    chrome.runtime.sendMessage({
        type: 'statusUpdate'
    }).catch(() => {});
}

// Handle messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === 'getStatus') {
        sendResponse({
            connected: socket && socket.readyState === WebSocket.OPEN,
            enabled: isEnabled,
            account: currentAccount
        });
    } else if (request.type === 'settingsChanged') {
        const { account, serverUrl, enabled } = request.settings;
        
        // Update settings
        if (account !== currentAccount) {
            currentAccount = account;
        }
        if (serverUrl !== serverUrl) {
            serverUrl = serverUrl;
            if (socket && socket.readyState === WebSocket.OPEN) {
                disconnect();
                setTimeout(connect, 100);
            }
        }
        
        // Handle enable/disable toggle
        if (enabled !== isEnabled) {
            isEnabled = enabled;
            if (isEnabled) {
                connect();
            } else {
                disconnect();
            }
        }
        
        sendResponse({ success: true });
    }
});

// Load settings on startup
chrome.storage.local.get(['enabled', 'account', 'serverUrl'], (settings) => {
    isEnabled = settings.enabled ?? false;
    currentAccount = settings.account || '';
    serverUrl = settings.serverUrl || DEFAULT_SERVER_URL;

    console.log('[CookieSync] Loaded settings:', {
        enabled: isEnabled,
        account: currentAccount,
        serverUrl: serverUrl
    });

    if (isEnabled && currentAccount) {
        connect();
    }
});

// Listen for storage changes
chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== 'local') return;

    if (changes.account) {
        currentAccount = changes.account.newValue || '';
    }
    if (changes.serverUrl) {
        serverUrl = changes.serverUrl.newValue || DEFAULT_SERVER_URL;
        if (socket && socket.readyState === WebSocket.OPEN) {
            disconnect();
            setTimeout(connect, 100);
        }
    }
});

