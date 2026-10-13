'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { randomUUID } = require('node:crypto');
const vm = require('node:vm');

const flush = () => new Promise(resolve => setImmediate(resolve));
const pair = [
    { name: 'ASP.NET_SessionId', value: 'existing-session', domain: '.reso.ru', path: '/' },
    { name: 'ResoOffice60', value: 'existing-office', domain: '.reso.ru', path: '/' },
];

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
    const installed = [];
    const written = [];
    const messages = [];
    const state = {
        tabs: [{ id: 7, url: 'https://office.reso.ru/', discarded: false }],
        cookies: structuredClone(pair),
        authenticated: true,
        contentScript: true,
        injectionAllowed: true,
        ...options,
    };
    let nextTimer = 0;
    const browser = {
        storage: {
            local: { get: async () => ({
                account: 'office_team', serverUrl: 'ws://127.0.0.1:52314',
                enabled: true, cookieDomains: ['.reso.ru'],
            }) },
            onChanged: event(),
        },
        runtime: {
            onMessage: event(), onInstalled: event(),
            sendMessage: async () => {},
        },
        alarms: { create() {}, clear() {}, onAlarm: event() },
        tabs: {
            query: async () => state.tabs,
            sendMessage: async () => {
                if (state.authReply) {
                    return state.authReply();
                }
                if (!state.contentScript) {
                    throw new Error('Receiving end does not exist');
                }
                return { authenticated: state.authenticated };
            },
            onUpdated: event(),
        },
        scripting: {
            executeScript: async details => {
                installed.push(details);
                if (!state.injectionAllowed) {
                    throw new Error('Missing host permission');
                }
                state.contentScript = true;
                return [{ frameId: 0 }];
            },
        },
        cookies: {
            getAll: async () => state.cookies,
            onChanged: event(),
            set: async details => {
                written.push(details);
                const cookie = { ...details, domain: details.domain || new URL(details.url).hostname };
                await browser.cookies.onChanged.emit({ cookie, removed: false, cause: 'explicit' });
                return cookie;
            },
        },
    };

    class Socket {
        static CONNECTING = 0;
        static OPEN = 1;
        constructor(url) {
            this.url = url;
            this.readyState = 0;
            this.events = new Map();
            sockets.push(this);
        }
        addEventListener(name, listener) {
            if (!this.events.has(name)) this.events.set(name, event());
            this.events.get(name).addListener(listener);
        }
        emit(name, data) { return this.events.get(name)?.emit(data); }
        open() { this.readyState = 1; return this.emit('open'); }
        send(data) { sent.push(JSON.parse(data)); }
        message(data) { return this.emit('message', { data: JSON.stringify(data) }); }
        close() { this.readyState = 3; return this.emit('close', { code: 1000 }); }
    }

    const context = vm.createContext({
        browser, WebSocket: Socket, URL, crypto: { randomUUID },
        console: Object.fromEntries(['log', 'warn', 'error', 'debug'].map(level => [
            level, (...args) => messages.push(args.join(' ')),
        ])),
        setTimeout: (callback, delay) => {
            const id = ++nextTimer;
            timers.set(id, { callback, delay });
            return id;
        },
        clearTimeout: id => timers.delete(id),
    });
    for (const file of ['logic.js', 'background.js']) {
        vm.runInContext(readFileSync(join(__dirname, '..', file), 'utf8'), context, { filename: file });
    }
    await flush();

    async function register(payload = [], result = true) {
        const socket = sockets.at(-1);
        const opening = socket.open();
        const request = sent.at(-1);
        assert.equal(request.command, 'register');
        await socket.message({
            uuid: request.uuid, result, message: result ? 'ok' : 'registration failed',
            payload, revision: payload.length ? 1 : 0, retry_after: 0,
        });
        await opening;
        await flush();
    }

    async function fireTimer(delay) {
        const entry = [...timers].find(([, timer]) => timer.delay === delay);
        assert.ok(entry, `Expected a ${delay}ms timer`);
        timers.delete(entry[0]);
        entry[1].callback();
        await flush();
    }

    const status = async () => (await browser.runtime.onMessage.emit({ type: 'getStatus' }))[0];
    return { state, sockets, sent, installed, written, messages, browser, timers, register, fireTimer, status };
}

test('initial registration uploads existing cookies without a cookies.onChanged event', async () => {
    const app = await background({ contentScript: false });
    await app.register();
    assert.deepEqual(app.sent.map(request => request.command), ['register']);
    await app.fireTimer(1500);
    assert.equal(app.installed.length, 1);
    assert.equal(app.installed[0].target.tabId, 7);
    assert.deepEqual(Array.from(app.installed[0].files), ['browser-polyfill.min.js', 'authentication.js']);
    assert.deepEqual(app.sent.map(request => request.command), ['register', 'set']);
    const request = app.sent[1];
    assert.equal(request.account, 'office_team');
    assert.notEqual(request.uuid, app.sent[0].uuid);
    assert.deepEqual(request.payload, pair);
    await app.sockets[0].message({ uuid: request.uuid, result: true, accepted: true, payload: pair });
    await flush();
    assert.equal((await app.status()).detail, '');
});

test('populated server account applies remote cookies without uploading the old local pair', async () => {
    const app = await background();
    const remote = pair.map(cookie => ({ ...cookie, value: `remote-${cookie.value}` }));
    await app.register(remote);
    assert.equal(app.written.length, 2);
    assert.deepEqual(app.written.map(cookie => cookie.value), remote.map(cookie => cookie.value));
    assert.deepEqual(app.sent.map(request => request.command), ['register']);
    assert.equal([...app.timers.values()].some(timer => timer.delay === 1500), false);
});

for (const [name, options] of [
    ['no office tab', { tabs: [] }],
    ['visible login dialog', { authenticated: false }],
    ['content script injection denied', { contentScript: false, injectionAllowed: false }],
]) {
    test(`initial upload is blocked with ${name}`, async () => {
        const app = await background(options);
        await app.register();
        await app.fireTimer(1500);
        assert.deepEqual(app.sent.map(request => request.command), ['register']);
        assert.match((await app.status()).detail, /Cookies не отправлены/);
        assert.ok(app.messages.some(message => message.includes('вход в РЕСО Офис не подтверждён')));
    });
}

test('unanswered authentication checks time out and never permit set', async () => {
    const app = await background({ authReply: () => new Promise(() => {}) });
    await app.register();
    await app.fireTimer(1500);
    await app.fireTimer(3000);
    await app.fireTimer(3000);
    assert.deepEqual(app.sent.map(request => request.command), ['register']);
    assert.match((await app.status()).detail, /Cookies не отправлены/);
});

test('opening an office tab retries a pending initial upload without changing cookies', async () => {
    const app = await background({ tabs: [] });
    await app.register();
    await app.fireTimer(1500);
    const tab = { id: 9, url: 'https://office.reso.ru/', discarded: false };
    app.state.tabs = [tab];
    await app.browser.tabs.onUpdated.emit(tab.id, { status: 'complete' }, tab);
    await app.fireTimer(1500);
    assert.deepEqual(app.sent.map(request => request.command), ['register', 'set']);
});

test('an incomplete local cookie pair is not uploaded at startup', async () => {
    const app = await background({ cookies: pair.slice(0, 1) });
    await app.register();
    await app.fireTimer(1500);
    assert.deepEqual(app.sent.map(request => request.command), ['register']);
    assert.match((await app.status()).detail, /нужна полная пара/);
});

test('registration failure and cookie events before registration do not permit set', async () => {
    const app = await background();
    await app.browser.cookies.onChanged.emit({ cookie: pair[0], removed: false });
    assert.equal(app.timers.size, 0);
    await app.register([], false);
    await app.browser.cookies.onChanged.emit({ cookie: pair[0], removed: false });
    assert.equal(app.timers.size, 0);
    assert.deepEqual(app.sent.map(request => request.command), ['register']);
});

for (const action of ['disable', 'change-account', 'server-push']) {
    test(`pending startup authentication cannot send stale cookies after ${action}`, async () => {
        let resolveAuth;
        const auth = new Promise(resolve => { resolveAuth = resolve; });
        const app = await background({ authReply: () => auth });
        await app.register();
        await app.fireTimer(1500);
        if (action === 'server-push') {
            await app.sockets[0].message({ command: 'set', payload: pair, revision: 1 });
        } else {
            const settings = action === 'disable' ? { enabled: false } : { account: 'another_team' };
            await app.browser.runtime.onMessage.emit({ type: 'settingsChanged', settings });
        }
        resolveAuth({ authenticated: true });
        await flush();
        assert.deepEqual(app.sent.map(request => request.command), ['register']);
    });
}
