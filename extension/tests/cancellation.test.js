'use strict';

/** @file Проверки освобождения подписок, результатов API и отмены ожиданий. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { createCancellationToken } = require('../logic.js');

test('a token preserves successful results and errors while remaining reusable', async () => {
    const token = createCancellationToken();
    const value = { tabId: 7 };
    assert.equal(await token.wait(Promise.resolve(value)), value);
    const error = new Error('API failed');
    await assert.rejects(token.wait(Promise.reject(error)), candidate => candidate === error);
    assert.equal(await token.wait(Promise.resolve(42)), 42);
    token.cancel();
});

test('cancellation releases all pending waits and consumes late API failures', async () => {
    const token = createCancellationToken();
    let resolve, reject;
    const first = token.wait(new Promise(done => { resolve = done; }));
    const second = token.wait(new Promise((done, fail) => { reject = fail; }));
    token.cancel();
    token.cancel();
    assert.deepEqual(await Promise.all([first, second]), [undefined, undefined]);
    resolve('late result');
    reject(new Error('late failure'));
    await new Promise(done => setImmediate(done));
    assert.equal(await token.wait(Promise.reject(new Error('already cancelled'))), undefined);
});

test('cancelling one token does not affect another live token', async () => {
    const first = createCancellationToken();
    const second = createCancellationToken();
    let release;
    const operation = new Promise(resolve => { release = resolve; });
    const cancelled = first.wait(operation);
    const live = second.wait(operation);
    first.cancel();
    assert.equal(await cancelled, undefined);
    release('available');
    assert.equal(await live, 'available');
});

test('a live token does not retain completed API snapshots until cancellation', () => {
    // Use a separate V8 process so GC is explicit and unrelated tests cannot
    // retain the snapshots. A job boundary releases WeakRef keep-alive roots.
    const result = spawnSync(process.execPath, ['--expose-gc', '-e', `
        const assert = require('node:assert/strict');
        const { createCancellationToken } = require(${JSON.stringify(require.resolve('../logic.js'))});
        (async () => {
            const token = createCancellationToken();
            const refs = [];
            async function read() {
                const snapshot = { id: refs.length };
                refs.push(new WeakRef(snapshot));
                return snapshot;
            }
            for (let i = 0; i < 200; i += 1) await token.wait(read());
            for (let i = 0; i < 4; i += 1) {
                await new Promise(resolve => setImmediate(resolve));
                global.gc();
            }
            assert.equal(refs.filter(ref => ref.deref()).length, 0);
            // Keep the uncancelled token reachable throughout the GC check.
            assert.equal(await token.wait(Promise.resolve('still live')), 'still live');
        })().catch(error => { console.error(error); process.exitCode = 1; });
    `], { encoding: 'utf8', timeout: 10000 });
    assert.ifError(result.error);
    assert.equal(result.status, 0, result.stderr || result.stdout);
});
