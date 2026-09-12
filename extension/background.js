const DEFAULT_SERVER_URL = 'wss://localhost:52314';
const DEFAULT_COOKIE_DOMAINS = ['.reso.ru'];
const DEFAULT_PROBE_URL = 'https://reso.ru/';
const RECONNECT_DELAY = 5000;
const REQUEST_TIMEOUT = 10000;
const SYNC_DEBOUNCE_MS = 1500;
const REMOTE_CHANGE_TTL_MS = 2000;
const PROBE_TIMEOUT_MS = 10000;
const PROBE_CACHE_TTL_MS = 30000;
const KEEPALIVE_ALARM = 'cookiesync-keepalive';
const KEEPALIVE_PERIOD_MINUTES = 0.5;

if (typeof importScripts === 'function') {
    importScripts('browser-polyfill.min.js');
    importScripts('logic.js');
}

let socket = null;
let isEnabled = false;
let currentAccount = '';
let currentServerUrl = DEFAULT_SERVER_URL;
let currentCookieDomains = [...DEFAULT_COOKIE_DOMAINS];
let currentProbeUrl = DEFAULT_PROBE_URL;
let reconnectTimeout = null;
let syncDebounceTimer = null;

// Текущий статус синхронизации: idle | connecting | connected | registering | online | disconnected | error
let syncPhase = 'idle';
let syncDetail = '';

// Последняя явная ошибка (показывается в popup, сбрасывается при успешном онлайн)
let lastError = '';

// Список ожидаемых удалённых изменений куки: domain|path|name -> timestamp
let expectedRemoteChanges = new Map();

// Кэш результата auth-пробы, чтобы не долбить сайт каждую синхронизацию
let authCache = { value: false, expiresAt: 0 };

class CookieSyncClient {
    constructor() {
        this.pendingRequests = new Map();
    }

    generateUuid() {
        if (typeof crypto !== 'undefined' && crypto.randomUUID) {
            return crypto.randomUUID();
        }
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
                }, REQUEST_TIMEOUT)
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
                const pending = this.pendingRequests.get(uuid);
                clearTimeout(pending.timeout);
                this.pendingRequests.delete(uuid);

                if (result) {
                    pending.resolve(payload);
                    if (payload) {
                        this.handleSetCookies(payload);
                    }
                } else {
                    pending.reject(new Error(message || 'Request failed'));
                }
            }
        } catch (e) {
            console.error('[CookieSync] Error parsing message:', e);
        }
    }

    handleSetCookies(payload) {
        if (!Array.isArray(payload)) {
            return;
        }

        const promises = payload
            .filter(cookie => cookie && cookie.name)
            .map(cookie => {
                remarkExpectedRemoteChange(expectedRemoteChanges, cookie);
                return this.setRemoteCookie(cookie);
            });

        Promise.all(promises).then(() => {
            notifyStatusUpdate();
        });
    }

    async setRemoteCookie(cookie) {
        const fallbackDomain = (currentCookieDomains[0] || DEFAULT_COOKIE_DOMAINS[0]);
        try {
            return await browser.cookies.set(buildCookieSetDetails(cookie, fallbackDomain));
        } catch (e) {
            console.error(
                `[CookieSync] Failed to set cookie "${cookie.name}":`,
                e && e.message ? e.message : e
            );
        }
    }
}

const client = new CookieSyncClient();

async function isAuthenticated() {
    const now = Date.now();
    if (now < authCache.expiresAt) {
        return authCache.value;
    }

    let authenticated = false;
    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);

    try {
        const response = await fetch(currentProbeUrl || DEFAULT_PROBE_URL, {
            credentials: 'include',
            redirect: 'follow',
            cache: 'no-store',
            signal: controller.signal
        });
        authenticated = response.ok;
    } catch (e) {
        console.error('[CookieSync] Auth probe failed:', e);
    } finally {
        clearTimeout(abortTimer);
    }

    authCache.value = authenticated;
    authCache.expiresAt = now + PROBE_CACHE_TTL_MS;
    return authenticated;
}

function scheduleCookieSync() {
    clearTimeout(syncDebounceTimer);
    syncDebounceTimer = setTimeout(() => {
        syncDebounceTimer = null;
        syncCookiesToServer();
    }, SYNC_DEBOUNCE_MS);
}

async function syncCookiesToServer() {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
        return;
    }
    if (!currentAccount) {
        return;
    }

    if (!(await isAuthenticated())) {
        console.warn('[CookieSync] Cookie sync skipped: auth probe failed or not authenticated');
        return;
    }

    const queries = currentCookieDomains.map(raw => browser.cookies.getAll({ domain: normalizeDomain(raw) }));
    const results = await Promise.all(queries);

    const seen = new Set();
    const cookies = [];
    for (const list of results) {
        for (const cookie of list) {
            const key = cookieKey(cookie);
            if (seen.has(key)) {
                continue;
            }
            seen.add(key);
            cookies.push(cookie);
        }
    }

    const payload = cookies
        .filter(cookie => isCookieForSyncDomain(cookie, currentCookieDomains))
        .map(pickCookieFields);

    if (!payload.length) {
        return;
    }

    try {
        await client.sendCommand('set', currentAccount, payload);
        console.log(`[CookieSync] Sent ${payload.length} cookies to server`);
    } catch (e) {
        console.error('[CookieSync] Failed to sync cookies to server:', e);
    }
}

function ensureKeepalive() {
    browser.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: KEEPALIVE_PERIOD_MINUTES });
}

function stopKeepalive() {
    browser.alarms.clear(KEEPALIVE_ALARM);
}

browser.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name !== KEEPALIVE_ALARM || !isEnabled) {
        return;
    }
    if (socket && socket.readyState === WebSocket.OPEN) {
        return;
    }
    console.log('[CookieSync] Keepalive: connection lost, reconnecting');
    scheduleReconnect();
});

function connect() {
    if (socket && socket.readyState === WebSocket.OPEN) {
        return;
    }

    console.log('[CookieSync] Connecting to:', currentServerUrl);
    setSyncPhase('connecting', currentServerUrl);

    try {
        socket = new WebSocket(currentServerUrl);

        socket.addEventListener('open', async () => {
            console.log('[CookieSync] Connected');
            clearTimeout(reconnectTimeout);
            reconnectTimeout = null;
            setSyncPhase('connected', 'Соединение установлено');

            if (currentAccount) {
                setSyncPhase('registering', currentAccount);
                try {
                    await client.register(currentAccount);
                    console.log('[CookieSync] Registered as:', currentAccount);
                    setSyncPhase('online', '');
                } catch (e) {
                    console.error('[CookieSync] Registration failed:', e);
                    setSyncPhase('error', 'Регистрация: ' + (e && e.message ? e.message : e));
                }
            } else {
                setSyncPhase('online', '');
            }
        });

        socket.addEventListener('message', (event) => {
            console.log('[CookieSync] Received:', event.data);
            client.handleMessage(event.data);
        });

socket.addEventListener('close', (event) => {
            console.log('[CookieSync] Disconnected', event && event.code, event && event.reason);
            if (isEnabled) {
                if (syncPhase !== 'error') {
                    const code = event && event.code;
                    const reason = (event && event.reason) ? `: ${event.reason}` : '';
                    if (code && code !== 1000) {
                        setSyncPhase('error', `Соединение разорвано (код ${code})${reason}`);
                    } else {
                        setSyncPhase('disconnected', 'Соединение потеряно' + (reason || ''));
                    }
                }
                scheduleReconnect();
            } else {
                setSyncPhase('idle', '');
            }
        });

        socket.addEventListener('error', (event) => {
            const reason = (event && event.error && event.error.message)
                ? event.error.message
                : `не удалось подключиться к ${currentServerUrl}`;
            console.error('[CookieSync] Socket error:', reason);
            setSyncPhase('error', 'Ошибка соединения: ' + reason);
        });
    } catch (e) {
        console.error('[CookieSync] Connection error:', e);
        setSyncPhase('error', 'Ошибка соединения: ' + (e && e.message ? e.message : e));
        if (isEnabled) {
            scheduleReconnect();
        }
    }
}

function disconnect() {
    stopKeepalive();
    clearTimeout(reconnectTimeout);
    reconnectTimeout = null;
    clearTimeout(syncDebounceTimer);
    syncDebounceTimer = null;
    if (socket) {
        socket.close();
        socket = null;
    }
    setSyncPhase('idle', '');
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
    browser.runtime.sendMessage({
        type: 'statusUpdate'
    }).catch(() => {});
}

function setSyncPhase(phase, detail) {
    syncPhase = phase;
    syncDetail = detail || '';
    if (phase === 'error') {
        lastError = syncDetail;
    } else if (phase === 'online') {
        lastError = '';
    }
    notifyStatusUpdate();
}

function handleSettingsChange(settings) {
    const { account, serverUrl: newServerUrl, enabled, cookieDomains, cookieDomain, probeUrl } = settings;

    if (account !== undefined) {
        currentAccount = account;
    }
    if (cookieDomains !== undefined || cookieDomain !== undefined) {
        const parsed = parseDomains(cookieDomains !== undefined ? cookieDomains : cookieDomain);
        currentCookieDomains = parsed.length ? parsed : [...DEFAULT_COOKIE_DOMAINS];
    }
    if (probeUrl !== undefined) {
        currentProbeUrl = probeUrl || DEFAULT_PROBE_URL;
    }
    if (newServerUrl !== undefined && newServerUrl !== currentServerUrl) {
        currentServerUrl = newServerUrl;
        if (socket && socket.readyState === WebSocket.OPEN) {
            disconnect();
            setTimeout(connect, 100);
        }
    }
    if (enabled !== undefined && enabled !== isEnabled) {
        isEnabled = enabled;
        if (isEnabled) {
            ensureKeepalive();
            connect();
        } else {
            stopKeepalive();
            disconnect();
        }
    }
}

async function loadSettings() {
    const settings = await browser.storage.local.get(
        ['enabled', 'account', 'serverUrl', 'cookieDomains', 'cookieDomain', 'probeUrl'],
    );
    const parsed = parseDomains(
        settings.cookieDomains !== undefined ? settings.cookieDomains : settings.cookieDomain
    );
    isEnabled = settings.enabled ?? false;
    currentAccount = settings.account || '';
    currentServerUrl = settings.serverUrl || DEFAULT_SERVER_URL;
    currentCookieDomains = parsed.length ? parsed : [...DEFAULT_COOKIE_DOMAINS];
    currentProbeUrl = settings.probeUrl || DEFAULT_PROBE_URL;

    console.log('[CookieSync] Loaded settings:', {
        enabled: isEnabled,
        account: currentAccount,
        serverUrl: currentServerUrl,
        cookieDomains: currentCookieDomains,
        probeUrl: currentProbeUrl
    });

    return settings;
}

// Handle messages from popup
browser.runtime.onMessage.addListener((request, sender) => {
    if (request.type === 'getStatus') {
        return Promise.resolve({
            connected: socket && socket.readyState === WebSocket.OPEN,
            enabled: isEnabled,
            phase: syncPhase,
            detail: syncDetail,
            account: currentAccount,
            serverUrl: currentServerUrl,
            cookieDomains: currentCookieDomains,
            probeUrl: currentProbeUrl,
            error: lastError
        });
    }

    if (request.type === 'settingsChanged') {
        handleSettingsChange(request.settings);
        return Promise.resolve({ success: true });
    }
});

// Local cookie changes: ignore other domains and self-applied remote changes,
// debounce, then push to server if authenticated.
browser.cookies.onChanged.addListener((changeInfo) => {
    const cookie = changeInfo.cookie;
    if (!isCookieForSyncDomain(cookie, currentCookieDomains)) {
        return;
    }
    if (isExpectedRemoteChange(expectedRemoteChanges, cookie, REMOTE_CHANGE_TTL_MS)) {
        return;
    }
    scheduleCookieSync();
});

// Listen for storage changes
browser.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== 'local') return;

    const newSettings = {};
    if (changes.account) {
        newSettings.account = changes.account.newValue || '';
    }
    if (changes.serverUrl) {
        newSettings.serverUrl = changes.serverUrl.newValue || DEFAULT_SERVER_URL;
    }
    if (changes.enabled) {
        newSettings.enabled = changes.enabled.newValue ?? false;
    }
    if (changes.cookieDomains) {
        newSettings.cookieDomains = changes.cookieDomains.newValue;
    } else if (changes.cookieDomain) {
        newSettings.cookieDomain = changes.cookieDomain.newValue;
    }
    if (changes.probeUrl) {
        newSettings.probeUrl = changes.probeUrl.newValue || DEFAULT_PROBE_URL;
    }
    handleSettingsChange(newSettings);
});

// Startup
browser.runtime.onInstalled?.addListener(() => {
    console.log('[CookieSync] Extension installed/updated');
});

loadSettings().then(() => {
    if (isEnabled && currentAccount) {
        ensureKeepalive();
        connect();
    }
});