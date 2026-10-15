'use strict';

/** @file Проверки DOM-вердикта входа, повторного внедрения и порядка наблюдений. */

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const { randomUUID, webcrypto } = require('node:crypto');

const source = readFileSync(join(__dirname, '../authentication.js'), 'utf8');

/**
 * Дважды внедряет content script в VM и проверяет единственность его слушателей.
 * @param {boolean} [legacy=false] Имитирует маркер внедрения предыдущей версии.
 * @param {boolean} [secure=true] Предоставляет randomUUID, как на HTTPS-странице.
 * @returns {Object} Управляемый DOM, запросы и записанные события состояния входа.
 */
function authentication(legacy = false, secure = true) {
    const listeners = [];
    const messages = [];
    const observers = [];
    const events = new Map();
    const state = { loginElement: null };
    const document = { readyState: 'complete', documentElement: {}, querySelector: () => state.loginElement,
        addEventListener: (name, callback) => events.set(name, callback) };
    const context = vm.createContext({
        location: { hostname: 'office.reso.ru' }, document,
        crypto: { ...(secure ? { randomUUID } : {}), getRandomValues: values => webcrypto.getRandomValues(values) },
        cookieSyncAuthInstalled: legacy,
        window: { addEventListener: (name, callback) => events.set(name, callback) },
        MutationObserver: class {
            constructor(callback) { observers.push(callback); }
            observe() {}
        },
        browser: { runtime: { onMessage: { addListener: listener => listeners.push(listener) },
            sendMessage: async message => { messages.push(message); } } },
    });
    vm.runInContext(source, context);
    vm.runInContext(source, context);
    assert.equal(listeners.length, 1);
    assert.equal(observers.length, 1);

    /** Вызывает обработчик запроса background и возвращает синхронный DOM-вердикт. */
    function query(type = 'cookiesyncCheckAuthState') {
        let reply;
        listeners[0]({ type }, {}, result => { reply = result; });
        return reply;
    }
    return { query, state, document, messages, observers, events };
}

test('authentication script can be injected twice and reports current login visibility', () => {
    const app = authentication();
    assert.equal(app.query('cookiesyncCheckAuth').authenticated, true);
    app.state.loginElement = { offsetParent: {}, getClientRects: () => [{}] };
    assert.equal(app.query().authenticated, false);
    app.state.loginElement = { offsetParent: null, getClientRects: () => [] };
    assert.equal(app.query().authenticated, true);
    app.document.readyState = 'loading';
    assert.equal(app.query().authenticated, false);
    assert.equal(app.query().ready, false);
});

test('login dialog transitions are reported even when no cookie changes occur afterwards', () => {
    const app = authentication();
    const documentId = app.messages[0].documentId;
    app.state.loginElement = { offsetParent: {}, getClientRects: () => [{}] };
    app.observers[0]();
    assert.equal(app.messages.at(-1).loginVisible, true);
    app.observers[0]();
    assert.equal(app.messages.length, 2);
    app.state.loginElement = { offsetParent: null, getClientRects: () => [] };
    app.observers[0]();
    assert.equal(app.messages.at(-1).authenticated, true);
    assert.equal(app.messages.at(-1).sequence, 3);
    assert.ok(app.messages.every(message => message.documentId === documentId));
});

test('a script from the previous release does not prevent installing the new observer', () => {
    const app = authentication(true);
    assert.equal(app.query().ready, true);
    assert.equal(app.messages.length, 1);
});

test('HTTP pages without crypto.randomUUID can still observe authentication', () => {
    const app = authentication(false, false);
    assert.equal(app.query().authenticated, true);
    assert.ok(app.query().documentId.length > 0);
});

test('an injection racing with navigation to another domain cannot confirm authentication', () => {
    let installed = false;
    const context = vm.createContext({
        location: { hostname: 'example.org' },
        browser: { runtime: { onMessage: { addListener: () => { installed = true; } } } },
    });
    vm.runInContext(source, context);
    assert.equal(installed, false);
});
