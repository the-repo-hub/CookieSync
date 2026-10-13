'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../authentication.js'), 'utf8');

test('authentication script can be injected twice and reports current login visibility', () => {
    const listeners = [];
    let loginElement = null;
    const document = { readyState: 'complete', querySelector: () => loginElement };
    const context = vm.createContext({
        location: { hostname: 'office.reso.ru' }, document,
        browser: { runtime: { onMessage: { addListener: listener => listeners.push(listener) } } },
    });
    vm.runInContext(source, context);
    vm.runInContext(source, context);
    assert.equal(listeners.length, 1);

    function authenticated() {
        let reply;
        listeners[0]({ type: 'cookiesyncCheckAuth' }, {}, result => { reply = result; });
        return reply.authenticated;
    }
    assert.equal(authenticated(), true);
    loginElement = { offsetParent: {}, getClientRects: () => [{}] };
    assert.equal(authenticated(), false);
    loginElement = { offsetParent: null, getClientRects: () => [] };
    assert.equal(authenticated(), true);
    document.readyState = 'loading';
    assert.equal(authenticated(), false);
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
