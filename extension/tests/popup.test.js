'use strict';

/** @file VM-тесты привязки popup к вкладке и подтверждённого сохранения настроек. */

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
/** Пропускает один оборот event loop для завершения загрузки UI через Promise. */
const flush = () => new Promise(resolve => setImmediate(resolve));

/**
 * Загружает popup с поддельными DOM и runtime; прямое обращение к storage запрещено.
 * @param {boolean} incognito Выбирает активную вкладку и её тестовый контекст.
 * @param {boolean} [enabled=false] Начальное подтверждённое состояние синхронизации.
 * @returns {Promise<Object>} DOM-элементы, запросы, слушатели и изменяемое состояние API.
 */
async function popup(incognito, enabled = false) {
    const elements = new Map();
    const requests = [];
    const messages = [];
    const state = { activeTabId: incognito ? 9 : 7, fail: false,
        settings: { account: incognito ? 'account_B' : 'account_A',
            serverUrl: 'ws://mnas:52314', cookieDomains: ['.reso.ru'], enabled } };
    /** Возвращает стабильную DOM-заглушку с классами и вручную вызываемыми событиями. */
    function element(id) {
        if (!elements.has(id)) {
            const classes = new Set();
            const listeners = new Map();
            elements.set(id, {
                value: '', checked: false, disabled: false, textContent: '',
                classList: { add: (...names) => names.forEach(name => classes.add(name)),
                    remove: (...names) => names.forEach(name => classes.delete(name)), contains: name => classes.has(name) },
                addEventListener: (name, callback) => listeners.set(name, callback),
                emit(name) { return listeners.get(name)?.call(this, {}); },
            });
        }
        return elements.get(id);
    }
    const browser = {
        tabs: { query: async () => [{ id: state.activeTabId, incognito }] },
        storage: { local: { get: () => { throw new Error('Popup must not read shared settings'); },
            set: () => { throw new Error('Popup must not persist shared settings'); } } },
        runtime: {
            onMessage: { addListener: callback => messages.push(callback) },
            sendMessage: async request => {
                requests.push(request);
                if (state.fail) throw new Error('Контекст закрыт');
                if (['saveSettings', 'disableContext'].includes(request.type)) {
                    if (state.saveGate) await state.saveGate;
                    if (state.failSave) throw new Error('Storage write failed');
                    state.settings = request.type === 'disableContext'
                        ? { ...state.settings, enabled: false } : { ...request.settings };
                    if (state.loseResponse) throw new Error('Response was lost');
                }
                return {
                    storeId: incognito ? '1' : '0', contextId: incognito ? 'private-id' : 'normal-id', incognito,
                    settings: { ...state.settings },
                    connected: false, phase: state.phase || 'idle', detail: '', error: '',
                };
            },
        },
    };
    const context = vm.createContext({ document: { getElementById: element }, browser, URL, console });
    for (const file of ['logic.js', 'popup.js']) {
        vm.runInContext(readFileSync(join(__dirname, '..', file), 'utf8'), context);
    }
    await flush();
    return { element, requests, messages, state, context };
}

test('popup binds account settings and saves to the active private context without storage.local', async () => {
    const app = await popup(true);
    assert.equal(app.requests[0].tabId, 9);
    assert.equal(app.element('accountInput').value, 'account_B');
    app.state.activeTabId = 7;
    app.element('accountInput').value = 'private_changed';
    await app.element('accountInput').emit('blur');
    const saved = app.requests.at(-1);
    assert.equal(saved.type, 'saveSettings');
    assert.equal(saved.tabId, 9);
    assert.equal(saved.contextId, 'private-id');
    assert.equal(saved.settings.account, 'private_changed');
});

test('popup ignores another context status and never falls back after its context closes', async () => {
    const app = await popup(true);
    const before = app.requests.length;
    app.messages[0]({ type: 'statusUpdate', contextId: 'normal-id' });
    await flush();
    assert.equal(app.requests.length, before);
    app.state.fail = true;
    app.messages[0]({ type: 'statusUpdate', contextId: 'private-id' });
    await flush();
    assert.match(app.element('syncStatus').textContent, /Контекст закрыт/);
    assert.equal(app.element('accountInput').value, 'account_B');
});

test('regular popup shows its account and rejects non-WebSocket URLs', async () => {
    const app = await popup(false);
    assert.equal(app.element('accountInput').value, 'account_A');
    app.element('serverUrlInput').value = 'https://mnas:52314';
    app.element('serverUrlInput').emit('input');
    assert.equal(app.element('enableToggle').disabled, true);
    assert.match(app.element('serverError').textContent, /ws:\/\//);
});

test('a failed disable save restores the confirmed enabled checkbox', async () => {
    const app = await popup(false, true);
    app.state.failSave = true;
    app.element('enableToggle').checked = false;
    await app.element('enableToggle').emit('change');
    assert.equal(app.element('enableToggle').checked, true);
    assert.equal(app.element('accountInput').disabled, true);
    assert.equal(app.state.settings.enabled, true);
    assert.equal(app.element('enableToggle').disabled, false);
    assert.match(app.element('syncStatus').textContent, /Storage write failed/);
    assert.equal(app.requests.at(-1).type, 'getContext');
});

test('toggle waits for confirmation and ignores blur saves while a toggle is pending', async () => {
    const app = await popup(false);
    let release;
    app.state.saveGate = new Promise(resolve => { release = resolve; });
    app.element('enableToggle').checked = true;
    const saving = app.element('enableToggle').emit('change');
    await flush();
    assert.equal(app.element('enableToggle').checked, false);
    assert.equal(app.element('enableToggle').disabled, true);
    app.element('accountInput').emit('blur');
    release(); await saving;
    assert.equal(app.element('enableToggle').checked, true);
    assert.equal(app.element('enableToggle').disabled, false);
    assert.equal(app.state.settings.enabled, true);
    assert.equal(app.requests.filter(request => request.type === 'saveSettings').length, 1);
});

test('a lost save response is reconciled with the actual background state', async () => {
    const app = await popup(true, true);
    app.state.loseResponse = true;
    app.element('enableToggle').checked = false;
    await app.element('enableToggle').emit('change');
    assert.equal(app.state.settings.enabled, false);
    assert.equal(app.element('enableToggle').checked, false);
    assert.equal(app.element('accountInput').disabled, false);
    assert.match(app.element('syncStatus').textContent, /Response was lost/);
});

test('a delayed status response cannot revert a confirmed toggle', async () => {
    const app = await popup(false, true);
    const send = app.context.browser.runtime.sendMessage;
    let deliver;
    let defer = true;
    app.context.browser.runtime.sendMessage = async request => {
        const status = await send(request);
        if (defer && request.type === 'getContext') {
            defer = false;
            await new Promise(resolve => { deliver = resolve; });
        }
        return status;
    };
    app.messages[0]({ type: 'statusUpdate', contextId: 'normal-id' });
    await flush();
    app.element('enableToggle').checked = false;
    await app.element('enableToggle').emit('change');
    deliver(); await flush();
    assert.equal(app.element('enableToggle').checked, false);
    assert.equal(app.state.settings.enabled, false);
});

test('status updates received during a toggle are refreshed after its acknowledgement', async () => {
    const app = await popup(false);
    const send = app.context.browser.runtime.sendMessage;
    app.context.browser.runtime.sendMessage = async request => {
        const status = await send(request);
        if (request.type === 'saveSettings') {
            app.state.phase = 'online';
            app.messages[0]({ type: 'statusUpdate', contextId: 'normal-id' });
            return { ...status, phase: 'connecting' };
        }
        return status;
    };
    app.element('enableToggle').checked = true;
    await app.element('enableToggle').emit('change');
    assert.equal(app.element('enableToggle').checked, true);
    assert.equal(app.element('syncStatus').textContent, 'Онлайн');
});

test('an invalid enabled URL does not lock out disabling and repairing the configuration', async () => {
    const app = await popup(false, true);
    app.state.settings.serverUrl = 'https://mnas:52314';
    await vm.runInContext('loadSettings()', app.context);
    assert.equal(app.element('enableToggle').checked, true);
    assert.equal(app.element('enableToggle').disabled, false);
    assert.match(app.element('serverError').textContent, /ws:\/\//);
    app.element('enableToggle').checked = false;
    await app.element('enableToggle').emit('change');
    assert.equal(app.requests.at(-1).type, 'disableContext');
    assert.equal('settings' in app.requests.at(-1), false);
    assert.equal(app.state.settings.enabled, false);
    assert.equal(app.state.settings.serverUrl, 'https://mnas:52314');
    assert.equal(app.element('serverUrlInput').disabled, false);
    assert.equal(app.element('enableToggle').disabled, true);
    app.element('serverUrlInput').value = 'ws://mnas:52314';
    app.element('serverUrlInput').emit('input');
    assert.equal(app.element('enableToggle').disabled, false);
    app.element('enableToggle').checked = true;
    await app.element('enableToggle').emit('change');
    assert.equal(app.state.settings.enabled, true);
    assert.equal(app.state.settings.serverUrl, 'ws://mnas:52314');
});

test('an enabled configuration with a missing account can still be disabled', async () => {
    const app = await popup(true, true);
    app.state.settings.account = '';
    await vm.runInContext('loadSettings()', app.context);
    assert.equal(app.element('enableToggle').disabled, false);
    app.element('enableToggle').checked = false;
    await app.element('enableToggle').emit('change');
    assert.equal(app.state.settings.enabled, false);
    assert.equal(app.element('accountInput').disabled, false);
});
