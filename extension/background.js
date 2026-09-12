const DEFAULT_SERVER_URL = 'wss://localhost:52314';
const DEFAULT_COOKIE_DOMAINS = ['.reso.ru'];
const RECONNECT_DELAY = 5000;
const REQUEST_TIMEOUT = 10000;
const SYNC_DEBOUNCE_MS = 1500;
const REMOTE_CHANGE_TTL_MS = 2000;
const AUTH_CHECK_DOMAIN = 'office.reso.ru';
const AUTH_CHECK_TIMEOUT_MS = 3000;
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
let reconnectTimeout = null;
let syncDebounceTimer = null;

// Текущий статус синхронизации: idle | connecting | connected | registering | online | disconnected | error
let syncPhase = 'idle';
let syncDetail = '';

// Последняя явная ошибка (показывается в popup, сбрасывается при успешном онлайн)
let lastError = '';

// Список ожидаемых удалённых изменений куки: domain|path|name -> timestamp
let expectedRemoteChanges = new Map();

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
    // Проверка выполняется content-script'ом на вкладках office.reso.ru:
    // аутентифицирован, если окно входа «Добро пожаловать в РЕСО Офис» не показано.
    if (!AUTH_CHECK_DOMAIN) {
        return true;
    }

    let tabs = [];
    try {
        tabs = await browser.tabs.query({ url: [`*://${AUTH_CHECK_DOMAIN}/*`] });
    } catch (e) {
        console.error('[CookieSync] Auth check: tabs.query failed:', e);
        return false;
    }

    const aliveTabs = tabs.filter(tab => typeof tab.id === 'number' && !tab.discarded);
    if (!aliveTabs.length) {
        console.warn(`[CookieSync] Auth check: нет открытой вкладки ${AUTH_CHECK_DOMAIN} — вход не подтверждён, set не отправляем`);
        return false;
    }

    let answered = 0;
    for (const tab of aliveTabs) {
        try {
            const reply = await withTimeout(
                browser.tabs.sendMessage(tab.id, { type: 'cookiesyncCheckAuth' }),
                AUTH_CHECK_TIMEOUT_MS,
            );
            if (reply && typeof reply.authenticated === 'boolean') {
                answered += 1;
                if (reply.authenticated) {
                    return true;
                }
            }
        } catch (e) {
            // вкладка ещё не загрузила content script — пробуем следующую
        }
    }

    if (answered) {
        return false;
    }
    console.warn(`[CookieSync] Auth check: ни одна вкладка ${AUTH_CHECK_DOMAIN} не ответила — вход не подтверждён`);
    return false;
}

function withTimeout(promise, milliseconds) {
    // В страницах/вкладках Chrome content script может "зависнуть"; ограничиваем ожидание.
    return new Promise((resolve) => {
        const timer = setTimeout(() => resolve(undefined), milliseconds);
        promise.then(
            value => { clearTimeout(timer); resolve(value); },
            () => { clearTimeout(timer); resolve(undefined); },
        );
    });
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
        console.warn('[CookieSync] Cookie sync skipped: вход в РЕСО Офис не подтверждён');
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

        socket.addEventListener('error', () => {
            const failedSocket = socket;
            setSyncPhase('error', `Ошибка соединения: не удалось подключиться к ${currentServerUrl}`);
            console.error(`[CookieSync] Socket error: не удалось подключиться к ${currentServerUrl}`);

            diagnoseConnection(currentServerUrl).then((diagnosis) => {
                if (diagnosis) {
                    console.warn('[CookieSync] Socket diagnosis:', diagnosis);
                    if (socket === failedSocket && syncPhase === 'error') {
                        setSyncPhase('error', `Ошибка соединения: ${diagnosis}`);
                    }
                }
            });
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

async function diagnoseConnection(url) {
    // WebSocket API не раскрывает причину обрыва (event.error пуст/нечитаем),
    // поэтому пробуем тот же host:port простым HTTP-запросом и по результату
    // строим осмысленное объяснение для пользователя.
    try {
        const wsUrl = new URL(url);
        const probeScheme = wsUrl.protocol === 'wss:' ? 'https' : 'http';
        const probeUrl = `${probeScheme}//${wsUrl.host}/`;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 4000);
        try {
            const response = await fetch(probeUrl, {
                cache: 'no-store',
                redirect: 'manual',
                signal: controller.signal,
            });
            clearTimeout(timer);
            return `На ${wsUrl.host} отвечает HTTP-сервер (код ${response.status}); WebSocket не может подключиться — возможно, сервер запущен без TLS (${'ws'} вместо ${'wss'}) либо порт занят другой службой`;
        } catch (fetchErr) {
            clearTimeout(timer);
            if (fetchErr && fetchErr.name === 'AbortError') {
                return `${wsUrl.host} не отвечает (таймаут) — проверьте запущен ли сервер, правила сети и файрвол`;
            }
            if (wsUrl.protocol === 'wss:') {
                return `Сертификат TLS недоверенный — браузер отклоняет wss://. Для самоподписанного сертификата запустите сервер с --no-tls и используйте ws://, либо добавьте сертификат в доверенные`;
            }
            return `Сервер на ${wsUrl.host} не отвечает — проверьте, запущен ли он и правильный ли порт (по умолчанию: 52314)`;
        }
    } catch (urlErr) {
        return `Некорректный адрес сервера: ${url}`;
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
    const { account, serverUrl: newServerUrl, enabled, cookieDomains, cookieDomain } = settings;

    if (account !== undefined) {
        currentAccount = account;
    }
    if (cookieDomains !== undefined || cookieDomain !== undefined) {
        const parsed = parseDomains(cookieDomains !== undefined ? cookieDomains : cookieDomain);
        currentCookieDomains = parsed.length ? parsed : [...DEFAULT_COOKIE_DOMAINS];
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
        ['enabled', 'account', 'serverUrl', 'cookieDomains', 'cookieDomain'],
    );
    const parsed = parseDomains(
        settings.cookieDomains !== undefined ? settings.cookieDomains : settings.cookieDomain
    );
    isEnabled = settings.enabled ?? false;
    currentAccount = settings.account || '';
    currentServerUrl = settings.serverUrl || DEFAULT_SERVER_URL;
    currentCookieDomains = parsed.length ? parsed : [...DEFAULT_COOKIE_DOMAINS];

    console.log('[CookieSync] Loaded settings:', {
        enabled: isEnabled,
        account: currentAccount,
        serverUrl: currentServerUrl,
        cookieDomains: currentCookieDomains
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