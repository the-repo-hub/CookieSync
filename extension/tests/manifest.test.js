'use strict';

/** @file Проверки CSP: явный ws/wss и отсутствие разрешения удалённых скриптов. */

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const manifest = JSON.parse(readFileSync(join(__dirname, '../manifest.json'), 'utf8'));

/** Проверяет наличие явной CSP и разбирает её в карту директива -> источники. */
function extensionPolicy() {
    const policy = manifest.content_security_policy?.extension_pages;
    // Firefox's implicit MV3 policy includes upgrade-insecure-requests.
    assert.equal(typeof policy, 'string', 'An explicit policy is required to support ws://');
    return new Map(policy.split(';').map(part => part.trim()).filter(Boolean).map(part => {
        const [directive, ...sources] = part.split(/\s+/);
        return [directive, sources];
    }));
}

test('manifest: user-selected ws:// is permitted without an automatic TLS upgrade', () => {
    const policy = extensionPolicy();
    assert.equal(policy.has('upgrade-insecure-requests'), false);
    assert.equal(policy.has('block-all-mixed-content'), false);
    const connections = policy.get('connect-src') || policy.get('default-src');
    assert.ok(connections, 'Declare the supported connection schemes explicitly');
    for (const scheme of ['ws:', 'wss:', 'http:', 'https:']) {
        assert.ok(connections.includes(scheme), `${scheme} is needed for WebSocket or diagnostics`);
    }
});

test('manifest: allowing plain WebSocket does not enable remote scripts or eval', () => {
    const policy = extensionPolicy();
    assert.deepEqual(policy.get('script-src'), ["'self'"]);
    assert.deepEqual(policy.get('object-src'), ["'none'"]);
});
