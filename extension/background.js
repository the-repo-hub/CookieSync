if (typeof importScripts === 'function') {
    importScripts('browser-polyfill.min.js', 'logic.js', 'sync-context.js');
}

const KEEPALIVE_ALARM = 'cookiesync-keepalive';
const contexts = new Map();
const retired = new Map();
const tabStores = new Map();
let localSettings = {};
let privateSessions = {};
let recoverySessions = {};
let recoveryWrites = Promise.resolve();
let legacySettings = null;
let operations = Promise.resolve();
let tabsVersion = 0;

function enqueue(operation) {
    const next = operations.then(operation);
    operations = next.catch(error => console.warn('[CookieSync] Context operation failed:', error));
    return next;
}

function notify(context) {
    // Only routing metadata is broadcast; account settings stay in their context.
    browser.runtime.sendMessage({
        type: 'statusUpdate', storeId: context.storeId, contextId: context.contextId,
    }).catch(() => {});
}

function saveRecoverySessions() {
    const snapshot = structuredClone(recoverySessions);
    const next = recoveryWrites.then(async () => {
        if (browser.storage.session) await browser.storage.session.set({ reauthContexts: snapshot });
    });
    recoveryWrites = next.catch(error => console.warn('[CookieSync] Could not persist login recovery:', error));
    return next;
}

function recoveryChanged(context) {
    if (contexts.get(context.storeId) !== context) return Promise.resolve();
    const record = context.snapshotRecovery();
    if (record) recoverySessions[context.storeId] = record;
    else delete recoverySessions[context.storeId];
    return saveRecoverySessions();
}

function retire(storeId) {
    const context = contexts.get(storeId);
    if (!context) return;
    contexts.delete(storeId);
    for (const [tabId, owner] of tabStores) {
        if (owner === storeId) tabStores.delete(tabId);
    }
    delete privateSessions[storeId];
    delete recoverySessions[storeId];
    saveRecoverySessions().catch(error => console.warn('[CookieSync] Could not clear retired recovery:', error));
    const done = context.dispose();
    retired.set(storeId, done);
    done.finally(() => { if (retired.get(storeId) === done) retired.delete(storeId); });
}

async function savePrivateSessions() {
    // storage.session is RAM-only and survives MV3 worker recreation, not a
    // browser restart. Never put private settings in storage.local/sync.
    if (browser.storage.session) {
        await browser.storage.session.set({ privateContexts: privateSessions });
    }
}

async function updateKeepalive() {
    if ([...contexts.values()].some(context => context.settings.enabled)) {
        await browser.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.5 });
    } else {
        await browser.alarms.clear(KEEPALIVE_ALARM);
    }
}

async function reconcile() {
    // Tab events update live state immediately while API calls are pending.
    // Retry any snapshot invalidated by those events instead of overwriting them.
    while (!await reconcileSnapshot()) { /* Retry with a fresh browser snapshot. */ }
}

async function reconcileSnapshot() {
    const version = tabsVersion;
    const [stores, tabs] = await Promise.all([browser.cookies.getAllCookieStores(), browser.tabs.query({})]);
    if (version !== tabsVersion) return false;
    const tabsById = new Map(tabs.map(tab => [tab.id, tab]));
    const active = new Set();
    const nextTabStores = new Map();
    for (const rawStore of stores) {
        if (version !== tabsVersion) return false;
        const tabIds = rawStore.tabIds.filter(id => tabsById.has(id));
        const incognito = rawStore.incognito === true || rawStore.id === '1' || rawStore.id === 'firefox-private'
            || tabIds.some(id => tabsById.get(id).incognito === true);
        if (incognito && !tabIds.length) continue;
        const store = { id: rawStore.id, tabIds, incognito };
        active.add(store.id);
        for (const id of tabIds) nextTabStores.set(id, store.id);
        let context = contexts.get(store.id);
        if (context && context.incognito && !tabIds.some(id => context.tabIds.has(id))) {
            retire(store.id);
            context = null;
        }
        if (!context) {
            // Don't let an already dispatched cookie operation from the previous
            // private lifetime overlap a newly created context with a reused ID.
            await retired.get(store.id);
            if (version !== tabsVersion) return false;
            let settings = localSettings[store.id];
            let contextId;
            if (incognito) {
                const session = privateSessions[store.id];
                if (session?.tabIds?.some(id => tabIds.includes(id))) {
                    settings = session.settings;
                    contextId = session.contextId;
                } else {
                    settings = normalizeSyncSettings();
                    delete privateSessions[store.id];
                }
            } else if (legacySettings && ['0', 'firefox-default', 'default'].includes(store.id)) {
                settings = settings || normalizeSyncSettings(legacySettings);
                localSettings[store.id] = settings;
                await browser.storage.local.set({ contextSettings: localSettings, contextSettingsVersion: 1 });
                legacySettings = null;
                if (version !== tabsVersion) return false;
            }
            context = new CookieSyncContext(store, settings, notify, contextId, recoveryChanged);
            contexts.set(store.id, context);
            // Lifecycle handlers must see a newly created context before the
            // first persistence await, including during worker restoration.
            for (const id of tabIds) tabStores.set(id, store.id);
            context.restoreRecovery(recoverySessions[store.id]);
            await recoveryChanged(context);
            if (version !== tabsVersion) return false;
        }
        context.tabIds = new Set(tabIds);
        if (incognito) {
            privateSessions[store.id] = {
                settings: context.settings, tabIds, contextId: context.contextId,
            };
        }
    }
    if (version !== tabsVersion) return false;
    tabStores.clear();
    for (const [tabId, storeId] of nextTabStores) tabStores.set(tabId, storeId);
    for (const id of contexts.keys()) {
        if (!active.has(id)) retire(id);
    }
    for (const id of Object.keys(privateSessions)) {
        if (!active.has(id)) delete privateSessions[id];
    }
    for (const id of Object.keys(recoverySessions)) {
        if (!active.has(id)) delete recoverySessions[id];
    }
    await savePrivateSessions();
    await saveRecoverySessions();
    await updateKeepalive();
    return version === tabsVersion;
}

const ready = enqueue(async () => {
    const stored = await browser.storage.local.get([
        'contextSettings', 'contextSettingsVersion', 'account', 'serverUrl', 'enabled', 'cookieDomains', 'cookieDomain',
    ]);
    localSettings = stored.contextSettings || {};
    if (stored.contextSettingsVersion !== 1) legacySettings = stored;
    if (browser.storage.session) {
        const session = await browser.storage.session.get(['privateContexts', 'reauthContexts']);
        privateSessions = session.privateContexts || {};
        recoverySessions = session.reauthContexts || {};
    }
    await reconcile();
});

async function contextForRequest(request) {
    if (!Number.isInteger(request.tabId)) throw new Error('Не удалось определить вкладку текущего контекста');
    const tab = await browser.tabs.get(request.tabId);
    const storeId = tabStores.get(tab.id);
    const context = contexts.get(storeId);
    if (!context || Boolean(tab.incognito) !== context.incognito
        || (request.contextId && request.contextId !== context.contextId)) {
        throw new Error('Контекст закрыт или изменился. Откройте окно расширения заново');
    }
    return context;
}

browser.runtime.onMessage.addListener((request, sender) => {
    if (request?.type === 'cookiesyncAuthState') {
        if (sender.id !== browser.runtime.id || !Number.isInteger(sender.tab?.id) || sender.frameId !== 0) return;
        try {
            const url = new URL(sender.url);
            if (!['http:', 'https:'].includes(url.protocol) || url.hostname !== 'office.reso.ru') return;
        } catch (error) { return; }
        const context = contexts.get(tabStores.get(sender.tab.id));
        const generation = context?.generation;
        return enqueue(async () => {
            await reconcile();
            if (context && contexts.get(tabStores.get(sender.tab.id)) === context && context.generation === generation) {
                const tab = await browser.tabs.get(sender.tab.id);
                try {
                    if (new URL(tab.url).hostname !== 'office.reso.ru') return;
                } catch (error) { return; }
                await context.authStateChanged(sender.tab.id, request);
            }
        });
    }
    if (!['getContext', 'saveSettings', 'disableContext'].includes(request?.type)) return;
    if (sender.id !== browser.runtime.id || sender.url !== browser.runtime.getURL('popup.html')) return;
    return enqueue(async () => {
        await reconcile();
        const context = await contextForRequest(request);
        if (request.type === 'saveSettings' || request.type === 'disableContext') {
            if (!request.contextId) throw new Error('Не указан идентификатор контекста');
            // Stopping an existing context must work even if its saved URL is
            // invalid. This operation cannot change any connection settings.
            const settings = request.type === 'disableContext'
                ? { ...context.settings, enabled: false }
                : validateSyncSettings(request.settings);
            if (context.incognito) {
                privateSessions[context.storeId] = {
                    settings, contextId: context.contextId, tabIds: [...context.tabIds],
                };
                await savePrivateSessions();
            } else {
                const updated = { ...localSettings, [context.storeId]: settings };
                await browser.storage.local.set({ contextSettings: updated, contextSettingsVersion: 1 });
                localSettings = updated;
            }
            if (contexts.get(context.storeId) !== context || !context.alive) {
                throw new Error('Контекст был закрыт во время сохранения');
            }
            context.configure(settings);
            await recoveryWrites;
            await updateKeepalive();
        }
        return context.status();
    });
});

browser.cookies.onChanged.addListener(change => contexts.get(change.cookie.storeId)?.cookieChanged(change));

browser.tabs.onCreated.addListener(tab => {
    tabsVersion += 1;
    // Update live IDs immediately, before asynchronous enumeration, so closing
    // another tab cannot mistakenly dispose a still-open private context.
    const context = contexts.get(tab.cookieStoreId) || (tab.incognito
        ? [...contexts.values()].find(candidate => candidate.incognito) : null);
    if (context) {
        context.tabIds.add(tab.id);
        tabStores.set(tab.id, context.storeId);
    }
    enqueue(reconcile);
});

browser.tabs.onRemoved.addListener(tabId => {
    tabsVersion += 1;
    const storeId = tabStores.get(tabId);
    const context = contexts.get(storeId);
    tabStores.delete(tabId);
    if (context) {
        context.tabRemoved(tabId);
        context.tabIds.delete(tabId);
        if (context.incognito && !context.tabIds.size) retire(storeId);
    }
    enqueue(reconcile);
});

browser.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    enqueue(async () => {
        await reconcile();
        contexts.get(tabStores.get(tabId))?.tabUpdated(tabId, changeInfo, tab);
    });
});

browser.alarms.onAlarm.addListener(alarm => {
    if (alarm.name !== KEEPALIVE_ALARM) return;
    enqueue(async () => {
        await reconcile();
        for (const context of contexts.values()) context.keepAlive();
    });
});

browser.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !changes.contextSettings) return;
    enqueue(async () => {
        localSettings = (await browser.storage.local.get('contextSettings')).contextSettings || {};
        for (const context of contexts.values()) {
            if (!context.incognito) context.configure(localSettings[context.storeId]);
        }
        await updateKeepalive();
    });
});
