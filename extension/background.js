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
let registeredSocket = null;
let initialSyncPending = false;
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
        this.remoteApplyQueue = Promise.resolve();
        this.latestRevision = -1;
        this.latestServerPayload = [];
        this.remoteGeneration = 0;
        this.remoteRetryTimeout = null;
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

    resetRemoteState() {
        this.remoteGeneration += 1;
        this.latestRevision = -1;
        this.latestServerPayload = [];
        clearTimeout(this.remoteRetryTimeout);
        this.remoteRetryTimeout = null;
    }

    rejectPendingForSocket(failedSocket, error) {
        for (const [uuid, pending] of this.pendingRequests) {
            if (pending.socket !== failedSocket) {
                continue;
            }
            clearTimeout(pending.timeout);
            this.pendingRequests.delete(uuid);
            pending.reject(error);
        }
    }

    async sendCommand(command, account, payload) {
        return new Promise((resolve, reject) => {
            if (!socket || socket.readyState !== WebSocket.OPEN) {
                reject(new Error('Socket not connected'));
                return;
            }

            const uuid = this.generateUuid();
            const requestSocket = socket;
            const message = {
                command,
                account,
                uuid,
                payload
            };

            this.pendingRequests.set(uuid, {
                resolve,
                reject,
                socket: requestSocket,
                timeout: setTimeout(() => {
                    this.pendingRequests.delete(uuid);
                    reject(new Error('Request timeout'));
                }, REQUEST_TIMEOUT)
            });

            try {
                requestSocket.send(JSON.stringify(message));
            } catch (e) {
                this.pendingRequests.delete(uuid);
                reject(e);
            }
        });
    }

    handleMessage(data, sourceSocket) {
        try {
            const response = JSON.parse(data);
            const { uuid, result, payload, command, message, revision } = response;

            if (command === 'set') {
                this.handleSetCookies(payload, revision);
                return;
            }

            if (uuid && this.pendingRequests.has(uuid)) {
                const pending = this.pendingRequests.get(uuid);
                if (pending.socket !== sourceSocket) {
                    return;
                }
                clearTimeout(pending.timeout);
                this.pendingRequests.delete(uuid);

                if (result) {
                    const shouldApply = payload && response.accepted !== true;
                    const applyPromise = shouldApply
                        ? this.handleSetCookies(payload, revision)
                        : Promise.resolve(true);
                    applyPromise.then(applied => pending.resolve({ ...response, applied }));
                } else {
                    pending.reject(new Error(message || 'Request failed'));
                }
            } else if (uuid && Array.isArray(payload) && Number.isInteger(revision)) {
                // Ответ мог прийти после локального timeout. Его серверная версия
                // всё равно нужна для восстановления заблокированного клиента.
                this.handleSetCookies(payload, revision);
            }
        } catch (e) {
            console.error('[CookieSync] Error parsing message:', e);
        }
    }

    handleSetCookies(payload, revision) {
        if (!Array.isArray(payload)) {
            return Promise.resolve();
        }

        const generation = this.remoteGeneration;
        const cookies = selectSyncCookiePair(payload, currentCookieDomains);
        if (!cookies.length) {
            if (payload.length) {
                console.error('[CookieSync] Server sent an incomplete or ambiguous cookie pair');
            }
            return Promise.resolve(false);
        }
        if (Number.isInteger(revision)) {
            if (revision < this.latestRevision) {
                return Promise.resolve(true);
            }
            if (revision > this.latestRevision) {
                clearTimeout(this.remoteRetryTimeout);
                this.remoteRetryTimeout = null;
            }
            this.latestRevision = revision;
        }
        this.latestServerPayload = cookies.map(cookie => ({ ...cookie }));
        // A peer may fill an initially empty account while we check authentication.
        initialSyncPending = false;

        const applyPayload = async () => {
            if (generation !== this.remoteGeneration) {
                return false;
            }
            if (Number.isInteger(revision) && revision < this.latestRevision) {
                return true;
            }

            for (const cookie of cookies) {
                let result = null;
                for (let attempt = 0; attempt < 3 && !result; attempt += 1) {
                    if (
                        generation !== this.remoteGeneration
                        || (Number.isInteger(revision) && revision < this.latestRevision)
                    ) {
                        return false;
                    }
                    remarkExpectedRemoteChange(expectedRemoteChanges, cookie);
                    result = await this.setRemoteCookie(cookie);
                    if (Number.isInteger(revision) && revision < this.latestRevision) {
                        return true;
                    }
                    if (!result && attempt < 2) {
                        await new Promise(resolve => setTimeout(resolve, 100 * (attempt + 1)));
                    }
                }
                if (!result) {
                    console.error('[CookieSync] Failed to apply the complete server cookie pair');
                    this.scheduleRemoteRetry(cookies, revision, generation);
                    return false;
                }
            }
            if (generation !== this.remoteGeneration) {
                return false;
            }
            notifyStatusUpdate();
            return true;
        };

        this.remoteApplyQueue = this.remoteApplyQueue
            .catch(() => {})
            .then(applyPayload);
        return this.remoteApplyQueue;
    }

    scheduleRemoteRetry(cookies, revision, generation) {
        if (
            this.remoteRetryTimeout
            || generation !== this.remoteGeneration
            || (Number.isInteger(revision) && revision < this.latestRevision)
        ) {
            return;
        }
        this.remoteRetryTimeout = setTimeout(() => {
            this.remoteRetryTimeout = null;
            if (generation === this.remoteGeneration && isEnabled) {
                this.handleSetCookies(cookies, revision);
            }
        }, 1000);
    }

    restoreLatestPair() {
        if (this.latestServerPayload.length !== 2) {
            return Promise.resolve(false);
        }
        return this.handleSetCookies(
            this.latestServerPayload,
            this.latestRevision,
        );
    }

    async setRemoteCookie(cookie) {
        const fallbackDomain = (currentCookieDomains[0] || DEFAULT_COOKIE_DOMAINS[0]);
        try {
            const result = await browser.cookies.set(
                buildCookieSetDetails(cookie, fallbackDomain)
            );
            const expectedValue = String(cookie.value !== undefined ? cookie.value : '');
            const domainMatches = result
                && normalizeDomain(result.domain) === normalizeDomain(cookie.domain);
            const pathMatches = result
                && result.path === (cookie.path || '/');
            const hostOnlyMatches = result
                && (
                    cookie.hostOnly === undefined
                    || result.hostOnly === cookie.hostOnly
                );
            if (
                !result
                || result.value !== expectedValue
                || !domainMatches
                || !pathMatches
                || !hostOnlyMatches
            ) {
                throw new Error('Browser did not persist the expected cookie');
            }
            return result;
        } catch (e) {
            console.error(
                `[CookieSync] Failed to set cookie "${cookie.name}":`,
                e && e.message ? e.message : e
            );
            return null;
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
            let reply = await withTimeout(
                browser.tabs.sendMessage(tab.id, { type: 'cookiesyncCheckAuth' }),
                AUTH_CHECK_TIMEOUT_MS,
            );
            if (!reply || typeof reply.authenticated !== 'boolean') {
                // Declarative content scripts aren't retroactively loaded into
                // pages that were already open when the extension was installed.
                const injected = await withTimeout(browser.scripting.executeScript({
                    target: { tabId: tab.id, frameIds: [0] },
                    files: ['browser-polyfill.min.js', 'authentication.js'],
                }), AUTH_CHECK_TIMEOUT_MS);
                if (!injected) {
                    console.warn(`[CookieSync] Auth check: не удалось подключить проверку к вкладке ${tab.id}`);
                    continue;
                }
                reply = await withTimeout(
                    browser.tabs.sendMessage(tab.id, { type: 'cookiesyncCheckAuth' }),
                    AUTH_CHECK_TIMEOUT_MS,
                );
            }
            if (reply && typeof reply.authenticated === 'boolean') {
                answered += 1;
                if (reply.authenticated) {
                    return true;
                }
            }
        } catch (e) {
            console.warn(`[CookieSync] Auth check: вкладка ${tab.id} недоступна`, e);
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

function scheduleCookieSync(initialOnly = false) {
    if (!isEnabled || !registeredSocket || registeredSocket !== socket) {
        return;
    }
    clearTimeout(syncDebounceTimer);
    syncDebounceTimer = setTimeout(() => {
        syncDebounceTimer = null;
        syncCookiesToServer(initialOnly);
    }, SYNC_DEBOUNCE_MS);
}

async function syncCookiesToServer(initialOnly = false) {
    const sourceSocket = socket;
    const account = currentAccount;
    const generation = client.remoteGeneration;
    const isCurrent = () => isEnabled && sourceSocket && socket === sourceSocket
        && registeredSocket === sourceSocket && sourceSocket.readyState === WebSocket.OPEN
        && currentAccount === account && client.remoteGeneration === generation;
    const canSend = () => isCurrent() && (!initialOnly || initialSyncPending);
    if (!account || !canSend()) {
        return;
    }

    try {
        const authenticated = await isAuthenticated();
        if (!canSend()) {
            return;
        }
        if (!authenticated) {
            console.warn('[CookieSync] Cookie sync skipped: вход в РЕСО Офис не подтверждён');
            if (initialSyncPending) {
                setSyncPhase('online', 'Cookies не отправлены: откройте office.reso.ru и подтвердите вход');
            }
            return;
        }

        const queries = currentCookieDomains.map(raw => browser.cookies.getAll({ domain: normalizeDomain(raw) }));
        const results = await Promise.all(queries);
        if (!canSend()) {
            return;
        }

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

        const pair = selectSyncCookiePair(cookies, currentCookieDomains);
        const payload = pair.map(pickCookieFields);

        if (payload.length !== 2) {
            const restored = await client.restoreLatestPair();
            console.warn(
                restored
                    ? '[CookieSync] Incomplete local cookie pair was restored from server state'
                    : '[CookieSync] Cookie sync skipped: complete cookie pair is not available'
            );
            if (isCurrent() && initialSyncPending) {
                setSyncPhase('online', 'Cookies не отправлены: нужна полная пара ASP.NET_SessionId и ResoOffice60');
            }
            return;
        }

        const response = await client.sendCommand('set', account, payload);
        if (!isCurrent()) {
            return;
        }
        if (response.accepted === false) {
            if (response.applied) {
                console.log(
                    `[CookieSync] Cookie update blocked for ${response.retry_after}s; server pair restored`
                );
            } else {
                console.error('[CookieSync] Cookie update blocked, but server pair could not be restored');
            }
        } else {
            initialSyncPending = false;
            console.log(`[CookieSync] Sent ${payload.length} cookies to server`);
        }
        setSyncPhase('online', '');
    } catch (e) {
        console.error('[CookieSync] Failed to sync cookies to server:', e);
        if (isCurrent() && initialSyncPending) {
            setSyncPhase('online', 'Cookies не отправлены: ошибка чтения или отправки, проверьте журнал расширения');
        }
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
    if (socket && (
        socket.readyState === WebSocket.OPEN
        || socket.readyState === WebSocket.CONNECTING
    )) {
        return;
    }

    console.log('[CookieSync] Connecting to:', currentServerUrl);
    setSyncPhase('connecting', currentServerUrl);

    try {
        const connection = new WebSocket(currentServerUrl);
        socket = connection;
        registeredSocket = null;
        initialSyncPending = false;

        connection.addEventListener('open', async () => {
            if (socket !== connection) {
                connection.close();
                return;
            }
            console.log('[CookieSync] Connected');
            clearTimeout(reconnectTimeout);
            reconnectTimeout = null;
            setSyncPhase('connected', 'Соединение установлено');

            if (currentAccount) {
                setSyncPhase('registering', currentAccount);
                try {
                    client.resetRemoteState();
                    const response = await client.register(currentAccount);
                    if (socket !== connection || !isEnabled) {
                        return;
                    }
                    registeredSocket = connection;
                    initialSyncPending = Array.isArray(response.payload)
                        && response.payload.length === 0 && client.latestServerPayload.length === 0;
                    console.log('[CookieSync] Registered as:', currentAccount);
                    setSyncPhase('online', initialSyncPending ? 'Проверка локальных cookies' : '');
                    if (initialSyncPending) {
                        scheduleCookieSync(true);
                    }
                } catch (e) {
                    if (socket !== connection || !isEnabled) {
                        return;
                    }
                    console.error('[CookieSync] Registration failed:', e);
                    setSyncPhase('error', 'Регистрация: ' + (e && e.message ? e.message : e));
                }
            } else {
                setSyncPhase('online', '');
            }
        });

        connection.addEventListener('message', (event) => {
            if (socket !== connection) {
                return;
            }
            console.log('[CookieSync] Received:', event.data);
            client.handleMessage(event.data, connection);
        });

        connection.addEventListener('close', (event) => {
            if (socket !== connection) {
                return;
            }
            socket = null;
            registeredSocket = null;
            initialSyncPending = false;
            client.rejectPendingForSocket(connection, new Error('Connection closed'));
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

        connection.addEventListener('error', () => {
            if (socket !== connection) {
                return;
            }
            const failedSocket = connection;
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
    registeredSocket = null;
    initialSyncPending = false;
    stopKeepalive();
    clearTimeout(reconnectTimeout);
    reconnectTimeout = null;
    clearTimeout(syncDebounceTimer);
    syncDebounceTimer = null;
    if (socket) {
        const closingSocket = socket;
        socket = null;
        client.rejectPendingForSocket(closingSocket, new Error('Client disconnected'));
        try {
            closingSocket.close();
        } catch (e) {
            console.warn('[CookieSync] Failed to close socket cleanly:', e);
        }
    }
    client.resetRemoteState();
    setSyncPhase('idle', '');
}

async function diagnoseConnection(url) {
    // WebSocket API не сообщает причину ошибки. Проверяем тот же host:port
    // сначала в ожидаемом, затем в альтернативном TLS-режиме.
    let wsUrl;
    try {
        wsUrl = new URL(url);
    } catch (urlErr) {
        return describeConnectionFailure(url, null, null);
    }

    const usesTls = wsUrl.protocol === 'wss:';
    const primaryScheme = usesTls ? 'https' : 'http';
    const alternateScheme = usesTls ? 'http' : 'https';
    const primary = await probeEndpoint(`${primaryScheme}://${wsUrl.host}/`);
    let alternate = { status: null, timedOut: false };
    if (primary.status === null) {
        alternate = await probeEndpoint(`${alternateScheme}://${wsUrl.host}/`);
    }
    return describeConnectionFailure(
        url,
        primary.status,
        alternate.status,
        primary.timedOut || alternate.timedOut,
    );
}

async function probeEndpoint(url) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    try {
        const response = await fetch(url, {
            cache: 'no-store',
            redirect: 'manual',
            signal: controller.signal,
        });
        return { status: response.status, timedOut: false };
    } catch (error) {
        return {
            status: null,
            timedOut: Boolean(error && error.name === 'AbortError'),
        };
    } finally {
        clearTimeout(timer);
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
    const wasEnabled = isEnabled;
    let connectionSettingsChanged = false;

    if (account !== undefined && account !== currentAccount) {
        currentAccount = account;
        connectionSettingsChanged = true;
    }
    if (cookieDomains !== undefined || cookieDomain !== undefined) {
        const parsed = parseDomains(cookieDomains !== undefined ? cookieDomains : cookieDomain);
        currentCookieDomains = parsed.length ? parsed : [...DEFAULT_COOKIE_DOMAINS];
    }
    if (newServerUrl !== undefined && newServerUrl !== currentServerUrl) {
        currentServerUrl = newServerUrl;
        connectionSettingsChanged = true;
    }
    if (enabled !== undefined) {
        isEnabled = enabled;
    }
    if (!isEnabled) {
        if (wasEnabled || socket) {
            disconnect();
        }
        return;
    }
    ensureKeepalive();
    if (connectionSettingsChanged && socket) {
        disconnect();
        ensureKeepalive();
        setTimeout(() => {
            if (isEnabled) {
                connect();
            }
        }, 100);
    } else if (!wasEnabled) {
        connect();
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
    if (!isCookieForSync(cookie, currentCookieDomains)) {
        return;
    }
    if (isExpectedRemoteChange(
        expectedRemoteChanges,
        cookie,
        REMOTE_CHANGE_TTL_MS,
        Date.now(),
        changeInfo.removed,
        changeInfo.cause,
    )) {
        return;
    }
    scheduleCookieSync();
});

// Retry the initial upload if the user opens/reloads the office tab after
// connecting. No cookie change is guaranteed to occur on an existing session.
browser.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (!initialSyncPending || changeInfo.status !== 'complete' || !tab.url) {
        return;
    }
    try {
        if (new URL(tab.url).hostname === AUTH_CHECK_DOMAIN) {
            scheduleCookieSync(true);
        }
    } catch (e) {
        console.debug('[CookieSync] Ignoring tab without a valid URL');
    }
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
