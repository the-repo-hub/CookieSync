'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { randomUUID } = require('node:crypto');
const vm = require('node:vm');

const flush = () => new Promise(resolve => setImmediate(resolve));
const pair = [
    { name: 'ASP.NET_SessionId', value: 'session-A', domain: '.reso.ru', path: '/' },
    { name: 'ResoOffice60', value: 'office-A', domain: '.reso.ru', path: '/' },
];
const pairB = pair.map(cookie => ({ ...cookie, value: `${cookie.value}-B` }));
const config = account => ({ account, serverUrl: 'ws://mnas:52314', enabled: true, cookieDomains: ['.reso.ru'] });
const normalTab = { id: 7, url: 'https://office.reso.ru/', incognito: false };
const privateTab = { id: 9, url: 'https://office.reso.ru/', incognito: true };

function event() {
    const listeners = [];
    return {
        addListener: listener => listeners.push(listener),
        emit: (...args) => Promise.all(listeners.map(listener => listener(...args))),
    };
}

async function background(options = {}) {
    const timers = new Map();
    const sockets = [];
    const sent = [];
    const written = [];
    const reads = [];
    const authTabs = [];
    const installed = [];
    const localWrites = [];
    const notices = [];
    const logs = [];
    const state = {
        tabs: [normalTab], cookies: structuredClone(pair), contentScript: true,
        authenticated: true, injectionAllowed: true,
        local: { contextSettingsVersion: 1, contextSettings: { '0': config('account_A') } },
        session: {}, ...options,
    };
    let timerId = 0;
    const sender = { id: 'extension-test', url: 'moz-extension://test/popup.html' };
    const browser = {
        runtime: {
            id: sender.id, getURL: path => `moz-extension://test/${path}`,
            onMessage: event(), sendMessage: async message => { notices.push(message); },
        },
        storage: { onChanged: event() },
        alarms: { create: async () => {}, clear: async () => {}, onAlarm: event() },
        tabs: {
            query: async options => state.tabs.filter(tab => !options.url || tab.url?.startsWith('https://office.reso.ru/')),
            get: async id => {
                const tab = state.tabs.find(tab => tab.id === id);
                if (!tab) throw new Error('Tab was closed');
                return tab;
            },
            sendMessage: async id => {
                authTabs.push(id);
                if (state.authReply) return state.authReply(id);
                if (!state.contentScript) throw new Error('Receiving end does not exist');
                if (state.authStateByTab?.[id]) return state.authStateByTab[id];
                return { authenticated: state.authByTab?.[id] ?? state.authenticated };
            },
            onCreated: event(), onRemoved: event(), onUpdated: event(),
        },
        scripting: { executeScript: async details => {
            installed.push(details);
            if (!state.injectionAllowed) throw new Error('Permission denied');
            state.contentScript = true;
            return [{ frameId: 0 }];
        } },
        cookies: {
            onChanged: event(),
            getAllCookieStores: async () => {
                if (state.storeQueryError) throw new Error('Store access failed');
                return structuredClone(state.stores || [
                    { id: '0', tabIds: state.tabs.filter(tab => !tab.incognito).map(tab => tab.id) },
                    ...(state.tabs.some(tab => tab.incognito)
                        ? [{ id: '1', tabIds: state.tabs.filter(tab => tab.incognito).map(tab => tab.id) }] : []),
                ]);
            },
            getAll: async details => {
                reads.push(details);
                assert.equal(typeof details.storeId, 'string');
                return (state.cookiesByStore?.[details.storeId] || state.cookies)
                    .map(cookie => ({ ...cookie, storeId: details.storeId }));
            },
            set: async details => {
                written.push(details);
                if (state.writeGate) await state.writeGate;
                if (state.failStoreIds?.includes(details.storeId)) throw new Error('Store write failed');
                const cookie = { ...details, domain: details.domain || new URL(details.url).hostname };
                await browser.cookies.onChanged.emit({ cookie, removed: false, cause: 'explicit' });
                return cookie;
            },
        },
    };
    for (const area of ['local', 'session']) {
        browser.storage[area] = {
            get: async () => structuredClone(state[area]),
            set: async values => {
                if (area === 'local' && state.storageError) throw new Error('Storage write failed');
                if (area === 'session' && values.reauthContexts && state.recoveryWriteGate) await state.recoveryWriteGate;
                const copy = structuredClone(values);
                if (area === 'local') localWrites.push(copy);
                const changes = {};
                for (const [key, value] of Object.entries(copy)) {
                    changes[key] = { oldValue: state[area][key], newValue: value };
                    state[area][key] = value;
                }
                await browser.storage.onChanged.emit(changes, area);
            },
        };
    }

    class Socket {
        static CONNECTING = 0;
        static OPEN = 1;
        constructor(url) { this.url = url; this.readyState = 0; this.events = new Map(); this.sent = []; sockets.push(this); }
        addEventListener(name, listener) {
            if (!this.events.has(name)) this.events.set(name, event());
            this.events.get(name).addListener(listener);
        }
        emit(name, data) { return this.events.get(name)?.emit(data); }
        open() { this.readyState = 1; return this.emit('open'); }
        send(data) { const request = JSON.parse(data); this.sent.push(request); sent.push(request); }
        message(data) { return this.emit('message', { data: JSON.stringify(data) }); }
        close() { this.readyState = 3; return this.emit('close', { code: 1000 }); }
    }

    const sandbox = vm.createContext({
        browser, WebSocket: Socket, URL, crypto: { randomUUID }, structuredClone,
        console: Object.fromEntries(['log', 'warn', 'error', 'debug'].map(level => [level, (...args) => logs.push(args.join(' '))])),
        setTimeout: (callback, delay) => { const id = ++timerId; timers.set(id, { callback, delay }); return id; },
        clearTimeout: id => timers.delete(id),
    });
    for (const file of ['logic.js', 'sync-context.js', 'background.js']) {
        vm.runInContext(readFileSync(join(__dirname, '..', file), 'utf8'), sandbox, { filename: file });
    }
    const settle = async () => {
        await flush(); await vm.runInContext('operations', sandbox);
        await vm.runInContext('recoveryWrites', sandbox); await flush();
    };
    await vm.runInContext('ready', sandbox);
    await settle();
    const context = (id = '0') => vm.runInContext(`contexts.get(${JSON.stringify(id)})`, sandbox);
    const request = async (message, source = sender) => (await browser.runtime.onMessage.emit(message, source))[0];
    const view = (tabId = 7, contextId) => request({ type: 'getContext', tabId, contextId });
    const authState = async (tabId, loginVisible, extra = {}) => {
        state.authStateByTab ||= {};
        const previous = state.authStateByTab[tabId];
        const message = { type: 'cookiesyncAuthState', documentId: `doc-${tabId}`,
            sequence: (previous?.sequence || 0) + 1, ready: true, loginVisible, authenticated: !loginVisible, ...extra };
        state.authStateByTab[tabId] = message;
        await request(message, { id: sender.id, url: 'https://office.reso.ru/', frameId: 0,
            tab: state.tabs.find(tab => tab.id === tabId) });
        await settle();
    };
    const save = async (settings, tabId = 7) => {
        const current = await view(tabId);
        const response = await request({
            type: 'saveSettings', tabId, contextId: current.contextId, settings: { ...current.settings, ...settings },
        });
        await settle();
        return response;
    };
    async function register(payload = [], result = true, storeId = '0', revision = payload.length ? 1 : 0) {
        const socket = context(storeId).socket;
        assert.ok(socket, `Expected an enabled context for store ${storeId}`);
        const opening = socket.open();
        const registration = socket.sent.at(-1);
        assert.equal(registration.command, 'register');
        await socket.message({ uuid: registration.uuid, result, message: 'test response', payload, revision, retry_after: 0 });
        await opening;
        await settle();
        return socket;
    }
    async function fireTimer(delay) {
        const entry = [...timers].find(([, timer]) => timer.delay === delay);
        assert.ok(entry, `Expected a ${delay}ms timer`);
        timers.delete(entry[0]); entry[1].callback(); await settle();
    }
    return { state, browser, sockets, sent, written, reads, authTabs, installed, localWrites, notices, logs,
        timers, context, request, view, save, register, fireTimer, settle, authState };
}

test('legacy settings migrate only to the regular context; private starts blank and disabled', async () => {
    const app = await background({ tabs: [normalTab, privateTab], local: config('old_regular') });
    assert.equal((await app.view(7)).settings.account, 'old_regular');
    const privateView = await app.view(9);
    assert.equal(privateView.settings.account, '');
    assert.equal(privateView.settings.enabled, false);
    assert.equal(privateView.incognito, true);
    assert.equal(app.sockets.length, 1);
    assert.equal(app.state.local.contextSettings['0'].account, 'old_regular');
    assert.equal('1' in app.state.local.contextSettings, false);
});

for (const [normalId, privateId] of [['0', '1'], ['firefox-default', 'firefox-private']]) {
    test(`different accounts and revision streams are isolated (${normalId}, ${privateId})`, async () => {
        const app = await background({
            tabs: [normalTab, privateTab],
            stores: [{ id: normalId, tabIds: [7] }, { id: privateId, tabIds: [9], incognito: true }],
            local: { contextSettingsVersion: 1, contextSettings: { [normalId]: config('account_A') } },
        });
        const regular = await app.register(pair, true, normalId, 100);
        assert.ok(app.written.every(cookie => cookie.storeId === normalId));
        await app.save(config('account_B'), 9);
        const privateSocket = await app.register(pairB, true, privateId, 1);
        assert.notEqual(regular, privateSocket);
        assert.equal(regular.sent[0].account, 'account_A');
        assert.equal(privateSocket.sent[0].account, 'account_B');
        assert.equal(app.written.filter(cookie => cookie.storeId === normalId).length, 2);
        assert.deepEqual(app.written.filter(cookie => cookie.storeId === privateId).map(cookie => cookie.value), pairB.map(cookie => cookie.value));
        await privateSocket.message({ command: 'set', payload: pairB, revision: 2 });
        await app.settle();
        assert.equal(app.written.filter(cookie => cookie.storeId === normalId).length, 2);
        assert.equal(app.written.filter(cookie => cookie.storeId === privateId).length, 4);
        assert.equal(app.timers.size, 0);
        assert.equal(JSON.stringify(app.localWrites).includes('account_B'), false);
        assert.ok(app.notices.every(message => !('account' in message) && !('settings' in message)));
    });
}

test('initial registration uploads the existing pair only from its own store', async () => {
    const app = await background({ tabs: [normalTab, privateTab], contentScript: false });
    await app.register();
    await app.fireTimer(1500);
    assert.deepEqual(app.sent.map(request => request.command), ['register', 'set']);
    assert.deepEqual(app.sent[1].payload, pair);
    assert.equal(app.reads[0].storeId, '0');
    assert.equal(app.installed[0].target.tabId, 7);
    const response = app.sent[1];
    await app.context().socket.message({ uuid: response.uuid, result: true, accepted: true, payload: pair, revision: 1 });
    await app.settle();
    assert.ok(app.written.every(cookie => cookie.storeId === '0'));
    assert.equal(app.context('1').settings.enabled, false);
    assert.equal(app.timers.size, 0);
});

for (const [name, options] of [
    ['no office tab', { tabs: [{ ...normalTab, url: 'https://example.com/' }] }],
    ['visible login dialog', { authenticated: false }],
    ['injection denied', { contentScript: false, injectionAllowed: false }],
]) {
    test(`initial upload is blocked with ${name}`, async () => {
        const app = await background(options);
        await app.register(); await app.fireTimer(1500);
        assert.deepEqual(app.sent.map(request => request.command), ['register']);
        assert.match(app.context().detail, /Cookies не отправлены/);
        assert.ok(app.logs.some(message => message.includes('вход в РЕСО Офис не подтверждён')));
    });
}

test('unanswered authentication times out without sending set', async () => {
    const app = await background({ authReply: () => new Promise(() => {}) });
    await app.register(); await app.fireTimer(1500);
    for (let i = 0; i < 4; i += 1) await app.fireTimer(3000);
    assert.deepEqual(app.sent.map(request => request.command), ['register']);
});

test('loading an office tab retries initial synchronization only in that context', async () => {
    const app = await background({ tabs: [{ ...normalTab, url: 'https://example.com/' }, privateTab] });
    await app.register(); await app.fireTimer(1500);
    app.state.tabs[0] = normalTab;
    await app.browser.tabs.onUpdated.emit(7, { status: 'complete' }, normalTab); await app.settle();
    await app.fireTimer(1500);
    assert.equal(app.sent.at(-1).command, 'set');
    assert.equal(app.sent.at(-1).account, 'account_A');
    assert.equal(app.sockets.length, 1);
});

test('cookie halves from regular and private stores are never combined', async () => {
    const app = await background({ tabs: [normalTab, privateTab], cookiesByStore: { '0': pair.slice(0, 1), '1': pairB.slice(1) } });
    await app.register(); await app.save(config('account_B'), 9); await app.register([], true, '1');
    await app.fireTimer(1500); await app.fireTimer(1500);
    assert.ok(app.sent.every(request => request.command === 'register'));
    assert.match(app.context().detail, /полная пара/);
    assert.match(app.context('1').detail, /полная пара/);
});

test('local cookie changes send the right pair to the right account over separate connections', async () => {
    const app = await background({ tabs: [normalTab, privateTab], cookiesByStore: { '0': pair, '1': pairB } });
    const regular = await app.register(pair);
    await app.save(config('account_B'), 9);
    const privateSocket = await app.register(pairB, true, '1');
    for (const storeId of ['0', '1']) {
        await app.browser.cookies.onChanged.emit({ cookie: { ...pair[0], storeId }, removed: false });
    }
    await app.fireTimer(1500); await app.fireTimer(1500);
    assert.equal(regular.sent.at(-1).account, 'account_A');
    assert.deepEqual(regular.sent.at(-1).payload, pair);
    assert.equal(privateSocket.sent.at(-1).account, 'account_B');
    assert.deepEqual(privateSocket.sent.at(-1).payload, pairB);
    assert.ok(app.sent.filter(request => request.command === 'set').every(request => request.payload.every(cookie => !('storeId' in cookie))));
});

test('authentication in a regular tab cannot authorize sending private cookies', async () => {
    const app = await background({ tabs: [normalTab, privateTab], authByTab: { 7: true, 9: false } });
    await app.register(pair); await app.save(config('account_B'), 9); await app.register(pairB, true, '1');
    app.authTabs.length = 0;
    await app.browser.cookies.onChanged.emit({ cookie: { ...pairB[0], storeId: '1' }, removed: false });
    await app.fireTimer(1500);
    assert.deepEqual(app.authTabs, [9]);
    assert.equal(app.reads.length, 0);
    assert.ok(app.sent.every(request => request.command === 'register'));
});

test('disabling or changing a private account does not touch the regular connection or state', async () => {
    const app = await background({ tabs: [normalTab, privateTab] });
    const regular = await app.register(pair);
    await app.save(config('account_B'), 9); const oldPrivate = await app.register(pairB, true, '1');
    await app.save({ enabled: false }, 9);
    assert.equal(oldPrivate.readyState, 3);
    assert.equal(regular.readyState, 1);
    await app.save(config('account_C'), 9);
    await app.register(pairB, true, '1');
    const count = app.written.length;
    await oldPrivate.message({ command: 'set', payload: pair, revision: 999 }); await app.settle();
    assert.equal(app.written.length, count);
    assert.equal(app.context().socket, regular);
    assert.equal(app.context().settings.account, 'account_A');
    assert.equal(app.context('1').settings.account, 'account_C');
});

test('private settings survive worker recreation in RAM but never go to disk', async () => {
    const first = await background({ tabs: [normalTab, privateTab] });
    await first.save(config('private-secret'), 9);
    const privateId = (await first.view(9)).contextId;
    assert.equal(JSON.stringify(first.state.local).includes('private-secret'), false);
    assert.equal(JSON.stringify(first.localWrites).includes('private-secret'), false);
    assert.equal(first.state.session.privateContexts['1'].settings.account, 'private-secret');
    const second = await background({ tabs: [normalTab, privateTab], local: structuredClone(first.state.local), session: structuredClone(first.state.session) });
    assert.equal(second.context('1').settings.account, 'private-secret');
    assert.equal(second.context('1').contextId, privateId);
    assert.equal(second.sockets.length, 2);
});

test('closing the last private tab forgets that context; reopening starts disabled with a new identity', async () => {
    const app = await background({ tabs: [normalTab, privateTab, { ...privateTab, id: 10 }] });
    const regular = await app.register(pair);
    await app.save(config('private-secret'), 9); const privateSocket = await app.register(pairB, true, '1');
    const oldId = app.context('1').contextId;
    app.state.tabs = app.state.tabs.filter(tab => tab.id !== 9);
    await app.browser.tabs.onRemoved.emit(9); await app.settle();
    assert.equal(app.context('1').contextId, oldId);
    assert.equal(privateSocket.readyState, 1);
    app.state.tabs = [normalTab];
    await app.browser.tabs.onRemoved.emit(10); await app.settle();
    assert.equal(app.context('1'), undefined);
    assert.equal(privateSocket.readyState, 3);
    assert.equal(regular.readyState, 1);
    assert.equal('1' in app.state.session.privateContexts, false);
    app.state.tabs.push({ ...privateTab, id: 11 });
    await app.browser.tabs.onCreated.emit(app.state.tabs[1]); await app.settle();
    const fresh = await app.view(11);
    assert.notEqual(fresh.contextId, oldId);
    assert.equal(fresh.settings.account, '');
    assert.equal(fresh.settings.enabled, false);
    const before = app.written.length;
    await privateSocket.message({ command: 'set', payload: pairB, revision: 20 }); await app.settle();
    assert.equal(app.written.length, before);
    await assert.rejects(app.request({ type: 'saveSettings', tabId: 11, contextId: oldId, settings: config('stale') }), /Контекст/);
});

test('a stale private session cannot be restored into a different lifetime after worker restart', async () => {
    const app = await background({
        tabs: [normalTab, { ...privateTab, id: 11 }],
        session: { privateContexts: { '1': { settings: config('old_private'), tabIds: [9], contextId: 'old-id' } } },
    });
    assert.equal(app.context('1').settings.enabled, false);
    assert.equal(app.context('1').settings.account, '');
    assert.equal(app.sockets.length, 1);
});

for (const action of ['disable', 'change-account', 'close-private']) {
    test(`pending authentication cannot send after ${action}`, async () => {
        let resolveAuth;
        const app = await background({ tabs: [normalTab, privateTab], authReply: () => new Promise(resolve => { resolveAuth = resolve; }) });
        await app.register(pair); await app.save(config('account_B'), 9); await app.register([], true, '1');
        await app.fireTimer(1500);
        if (action === 'close-private') {
            app.state.tabs = [normalTab]; await app.browser.tabs.onRemoved.emit(9); await app.settle();
        } else await app.save(action === 'disable' ? { enabled: false } : { account: 'account_C' }, 9);
        resolveAuth({ authenticated: true }); await app.settle();
        assert.ok(app.sent.every(request => request.command === 'register'));
    });
}

test('late cookie writes from an old account cannot overwrite the newly selected account', async () => {
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    const app = await background({ writeGate: gate });
    const first = app.register(pair); await flush();
    await app.save(config('account_B'));
    const second = app.register(pairB); await flush();
    release(); await first; await second; await app.settle();
    assert.deepEqual(app.written.map(cookie => cookie.value), [pair[0].value, ...pairB.map(cookie => cookie.value)]);
});

test('remote cookies never fall back to another store if the target store fails', async () => {
    const app = await background({ tabs: [normalTab, privateTab], failStoreIds: ['1'] });
    await app.register(pair); await app.save(config('account_B'), 9); await app.register(pairB, true, '1');
    assert.equal(app.written.filter(cookie => cookie.storeId === '0').length, 2);
    assert.equal(app.written.filter(cookie => cookie.storeId === '1').length, 1);
    app.state.tabs = [normalTab]; await app.browser.tabs.onRemoved.emit(9); await app.settle();
    assert.equal(app.timers.size, 0);
});

test('popup context selection fails closed for missing tabs, stale identities and content-script senders', async () => {
    const app = await background({ tabs: [normalTab, privateTab] });
    await assert.rejects(app.view(99), /closed/);
    await assert.rejects(app.request({ type: 'getContext' }), /вкладку/);
    const status = await app.view(7);
    assert.equal(await app.request({ type: 'saveSettings', tabId: 9, contextId: status.contextId, settings: config('bad') },
        { id: 'extension-test', url: 'https://office.reso.ru/' }), undefined);
    assert.equal(app.context('1').settings.account, '');
});

test('storage write failure does not apply unsaved regular settings', async () => {
    const app = await background({ storageError: true });
    await assert.rejects(app.save(config('unsaved')), /Storage write failed/);
    assert.equal(app.context().settings.account, 'account_A');
});

test('reconnecting a private socket does not reset or duplicate the regular connection', async () => {
    const app = await background({ tabs: [normalTab, privateTab] });
    const regular = await app.register(pair);
    await app.save(config('account_B'), 9);
    const privateSocket = await app.register(pairB, true, '1');
    await privateSocket.close(); await app.settle();
    assert.equal(regular.readyState, 1);
    await app.fireTimer(5000);
    const replacement = await app.register(pairB, true, '1');
    assert.notEqual(replacement, privateSocket);
    assert.equal(replacement.sent[0].account, 'account_B');
    await app.browser.alarms.onAlarm.emit({ name: 'cookiesync-keepalive' }); await app.settle();
    assert.equal(app.sockets.length, 3);
    assert.equal(app.context().socket, regular);
});

test('concurrent saves keep independent accounts and never persist private settings on disk', async () => {
    const app = await background({ tabs: [normalTab, privateTab] });
    await Promise.all([app.save(config('regular_updated'), 7), app.save(config('private_secret'), 9)]);
    await app.settle();
    assert.equal(app.context().settings.account, 'regular_updated');
    assert.equal(app.context('1').settings.account, 'private_secret');
    assert.equal(app.state.local.contextSettings['0'].account, 'regular_updated');
    assert.equal(JSON.stringify(app.localWrites).includes('private_secret'), false);
});

test('a Firefox container is a separate persisted context and does not inherit the default account', async () => {
    const container = { id: 12, url: 'https://office.reso.ru/', incognito: false, cookieStoreId: 'firefox-container-1' };
    const app = await background({
        tabs: [normalTab, container],
        stores: [{ id: '0', tabIds: [7] }, { id: 'firefox-container-1', tabIds: [12], incognito: false }],
    });
    assert.equal((await app.view(12)).settings.account, '');
    await app.register(pair);
    await app.save(config('container_C'), 12);
    await app.register(pairB, true, 'firefox-container-1');
    assert.equal(app.state.local.contextSettings['firefox-container-1'].account, 'container_C');
    assert.equal(app.state.local.contextSettings['0'].account, 'account_A');
    assert.deepEqual(app.written.map(cookie => cookie.storeId), ['0', '0', 'firefox-container-1', 'firefox-container-1']);
});

test('a fresh login refreshes the observed revision even when cookies changed before the dialog disappeared', async () => {
    const app = await background();
    const socket = await app.register(pair, true, '0', 5);
    await app.authState(7, true);
    assert.equal(app.context().recovery.expectedRevision, 5);
    app.state.cookies = pairB;
    await app.browser.cookies.onChanged.emit({ cookie: { ...pairB[0], storeId: '0' }, removed: false });
    await app.fireTimer(1500);
    assert.deepEqual(app.sent.map(request => request.command), ['register']);
    await app.authState(7, false); // No more cookies.onChanged events after this.
    await app.fireTimer(1500);
    const request = app.sent.at(-1);
    assert.equal(request.command, 'refresh');
    assert.equal(request.expected_revision, 5);
    assert.deepEqual(request.payload, pairB);
    await socket.message({ command: 'set', payload: pair, revision: 5 });
    await app.settle();
    assert.equal(app.written.length, 2, 'old server cookies must not overwrite the freshly logged-in pair');
    await socket.message({ uuid: request.uuid, result: true, accepted: true, payload: pairB, revision: 6 });
    await app.settle();
    assert.equal(app.context().recovery, null);
    assert.equal(app.context().latestRevision, 6);
    assert.deepEqual(app.written.slice(-2).map(cookie => cookie.value), pairB.map(cookie => cookie.value));
    assert.equal(app.timers.size, 0);
    assert.equal('expectedRevision' in app.state.session.reauthContexts['0'], false);
});

test('seeing an already authenticated page does not grant cooldown bypass', async () => {
    const app = await background();
    await app.register(pair);
    await app.authState(7, false);
    assert.equal(app.context().recovery, null);
    app.state.cookies = pairB;
    await app.browser.cookies.onChanged.emit({ cookie: { ...pairB[0], storeId: '0' }, removed: false });
    await app.fireTimer(1500);
    assert.equal(app.sent.at(-1).command, 'set');
    assert.equal('expected_revision' in app.sent.at(-1), false);
});

test('an incomplete new pair is not restored from the known failed server session', async () => {
    const app = await background();
    await app.register(pair);
    await app.authState(7, true);
    app.state.cookies = pairB.slice(0, 1);
    await app.authState(7, false);
    await app.fireTimer(1500);
    assert.equal(app.sent.length, 1);
    assert.equal(app.written.length, 2);
    assert.equal(app.context().recovery.ready, true);
    app.state.cookies = pairB;
    await app.browser.cookies.onChanged.emit({ cookie: { ...pairB[1], storeId: '0' }, removed: false });
    await app.fireTimer(1500);
    assert.equal(app.sent.at(-1).command, 'refresh');
});

test('duplicate notifications and cookie events cannot send concurrent refresh requests', async () => {
    const app = await background();
    await app.register(pair);
    await app.authState(7, true);
    app.state.cookies = pairB;
    await app.authState(7, false);
    await app.fireTimer(1500);
    for (let i = 0; i < 2; i += 1) {
        await app.browser.cookies.onChanged.emit({ cookie: { ...pairB[0], storeId: '0' }, removed: false });
        await app.fireTimer(1500);
        assert.equal(app.context().recovery.inFlight, true);
    }
    assert.equal(app.sent.filter(request => request.command === 'refresh').length, 1);
});

test('a revision conflict adopts the winner and never retries with a rebased revision', async () => {
    const app = await background();
    const socket = await app.register(pair, true, '0', 5);
    await app.authState(7, true);
    app.state.cookies = pairB;
    await app.authState(7, false);
    await app.fireTimer(1500);
    const request = app.sent.at(-1);
    const winner = pair.map(cookie => ({ ...cookie, value: `${cookie.value}-winner` }));
    await socket.message({ uuid: request.uuid, result: true, accepted: false, payload: winner, revision: 6 });
    await app.settle();
    assert.equal(app.context().recovery, null);
    assert.deepEqual(app.written.slice(-2).map(cookie => cookie.value), winner.map(cookie => cookie.value));
    assert.equal(app.sent.filter(request => request.command === 'refresh').length, 1);
    assert.match(app.context().detail, /Другой клиент/);
    assert.equal(app.timers.size, 0);
});

test('a peer update cancels an older login fence, including after worker recreation', async () => {
    const app = await background();
    const socket = await app.register(pair, true, '0', 5);
    await app.authState(7, true);
    await socket.message({ command: 'set', payload: pairB, revision: 6 });
    await app.settle();
    assert.equal(app.context().recovery, null);
    const resumed = await background({
        local: structuredClone(app.state.local), session: structuredClone(app.state.session),
        authStateByTab: structuredClone(app.state.authStateByTab),
    });
    await resumed.register(pairB, true, '0', 6);
    assert.equal(resumed.context().recovery, null, 'the same old visible dialog must not be rebased onto revision 6');
    await resumed.authState(7, false);
    assert.equal(resumed.timers.size, 0);
    assert.ok(resumed.sent.every(request => request.command === 'register'));
});

test('recovery survives worker recreation without applying the old registration pair', async () => {
    const app = await background();
    await app.register(pair, true, '0', 5);
    await app.authState(7, true);
    await app.authState(7, false);
    const resumed = await background({
        local: structuredClone(app.state.local), session: structuredClone(app.state.session),
        authStateByTab: structuredClone(app.state.authStateByTab), cookies: pairB,
    });
    await resumed.register(pair, true, '0', 5);
    assert.equal(resumed.written.length, 0);
    await resumed.fireTimer(1500);
    assert.equal(resumed.sent.at(-1).command, 'refresh');
    assert.equal(resumed.sent.at(-1).expected_revision, 5);
    assert.deepEqual(resumed.sent.at(-1).payload, pairB);
    assert.equal(JSON.stringify(resumed.state.session).includes(pairB[0].value), false);
});

test('network reconnect retains the original login revision and fresh local cookies', async () => {
    const app = await background();
    const socket = await app.register(pair, true, '0', 5);
    await app.authState(7, true);
    app.state.cookies = pairB;
    await app.authState(7, false);
    await socket.close(); await app.settle();
    await app.fireTimer(5000);
    app.written.length = 0;
    await app.register(pair, true, '0', 5);
    assert.equal(app.written.length, 0);
    await app.fireTimer(1500);
    assert.equal(app.sent.at(-1).command, 'refresh');
    assert.equal(app.sent.at(-1).expected_revision, 5);
});

test('an unsupported server reports an error without restoring the failed old session', async () => {
    const app = await background();
    const socket = await app.register(pair);
    await app.authState(7, true);
    app.state.cookies = pairB;
    await app.authState(7, false);
    await app.fireTimer(1500);
    await socket.message({ uuid: app.sent.at(-1).uuid, result: false, message: "Command 'refresh' does not exist" });
    await app.settle();
    await socket.message({ command: 'set', payload: pair, revision: 1 }); await app.settle();
    assert.equal(app.written.length, 2);
    assert.match(app.context().error, /версию сервера/);
    assert.equal(app.context().recovery.ready, true);
});

test('late refresh acknowledgement after timeout resolves recovery using the accepted server revision', async () => {
    const app = await background();
    const socket = await app.register(pair);
    await app.authState(7, true);
    app.state.cookies = pairB;
    await app.authState(7, false);
    await app.fireTimer(1500);
    const uuid = app.sent.at(-1).uuid;
    await app.fireTimer(10000);
    assert.equal(app.context().recovery.ready, true);
    await socket.message({ uuid, result: true, accepted: true, payload: pairB, revision: 2 });
    await app.settle();
    assert.equal(app.context().recovery, null);
    assert.equal(app.context().phase, 'online');
    assert.deepEqual(app.written.slice(-2).map(cookie => cookie.value), pairB.map(cookie => cookie.value));
});

test('reauthentication messages are routed by sender tab and cannot affect another context', async () => {
    const app = await background({ tabs: [normalTab, privateTab] });
    await app.register(pair, true, '0', 100);
    await app.save(config('account_B'), 9);
    await app.register(pair, true, '1', 2);
    await app.authState(9, true);
    app.state.cookiesByStore = { '1': pairB, '0': pair };
    await app.authState(9, false);
    await app.fireTimer(1500);
    assert.equal(app.sent.at(-1).command, 'refresh');
    assert.equal(app.sent.at(-1).account, 'account_B');
    assert.equal(app.sent.at(-1).expected_revision, 2);
    assert.equal(app.context().recovery, null);
    assert.equal(JSON.stringify(app.localWrites).includes('expectedRevision'), false);
    app.state.tabs = [normalTab];
    await app.browser.tabs.onRemoved.emit(9); await app.settle();
    assert.equal('1' in app.state.session.reauthContexts, false);
});

test('untrusted frames, foreign sites and loading documents cannot start recovery', async () => {
    const app = await background();
    await app.register(pair);
    const message = { type: 'cookiesyncAuthState', documentId: 'fake', sequence: 1,
        ready: true, loginVisible: true, authenticated: false };
    for (const source of [
        { id: 'extension-test', url: 'https://office.reso.ru/', tab: normalTab, frameId: 1 },
        { id: 'extension-test', url: 'https://evilreso.ru/', tab: normalTab, frameId: 0 },
    ]) await app.request(message, source);
    await app.authState(7, true, { ready: false });
    assert.equal(app.context().recovery, null);
});

test('a login transition across document navigation is accepted but an old document cannot rearm it', async () => {
    const app = await background();
    const socket = await app.register(pair);
    await app.authState(7, true, { documentId: 'login-page', sequence: 1 });
    await app.authState(7, false, { documentId: 'office-page', sequence: 1 });
    assert.equal(app.context().recovery.ready, true);
    await socket.message({ command: 'set', payload: pairB, revision: 2 }); await app.settle();
    await app.authState(7, true, { documentId: 'login-page', sequence: 99 });
    assert.equal(app.context().recovery, null);
});

test('changing account while a refresh reply awaits session storage cannot apply the old account cookies', async () => {
    const app = await background();
    const socket = await app.register(pair);
    await app.authState(7, true);
    app.state.cookies = pairB;
    await app.authState(7, false);
    await app.fireTimer(1500);
    let release;
    app.state.recoveryWriteGate = new Promise(resolve => { release = resolve; });
    await socket.message({ uuid: app.sent.at(-1).uuid, result: true, accepted: true, payload: pairB, revision: 2 });
    await flush();
    app.context().configure(config('account_C'));
    release();
    await app.settle();
    assert.equal(app.context().settings.account, 'account_C');
    assert.equal(app.written.length, 2);
    assert.equal(app.context().latestPayload.length, 0);
});

test('closing or navigating away from the login tab clears its recovery metadata', async () => {
    const app = await background();
    await app.register(pair);
    await app.authState(7, true);
    app.state.tabs = [{ ...normalTab, url: 'https://example.com/' }];
    await app.browser.tabs.onUpdated.emit(7, { status: 'complete', url: 'https://example.com/' }, app.state.tabs[0]);
    await app.settle();
    assert.equal(app.context().recovery, null);
    assert.equal('0' in app.state.session.reauthContexts, false);
    app.state.tabs = [normalTab];
    await app.authState(7, true);
    app.state.tabs = [];
    await app.browser.tabs.onRemoved.emit(7); await app.settle();
    assert.equal('0' in app.state.session.reauthContexts, false);
});

test('login in another observed office tab of the same store uses that tab revision', async () => {
    const otherTab = { ...normalTab, id: 10 };
    const app = await background({ tabs: [normalTab, otherTab] });
    await app.register(pair, true, '0', 5);
    await app.authState(7, true);
    await app.authState(10, true);
    assert.equal(app.context().recovery.tabId, 7);
    app.state.cookies = pairB;
    await app.authState(10, false);
    app.authTabs.length = 0;
    await app.fireTimer(1500);
    assert.deepEqual(app.authTabs, [10]);
    assert.equal(app.sent.at(-1).command, 'refresh');
    assert.equal(app.sent.at(-1).expected_revision, 5);
    assert.deepEqual(app.sent.at(-1).payload, pairB);
});
