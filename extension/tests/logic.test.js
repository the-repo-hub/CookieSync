'use strict';

/** @file Проверки чистых функций доменов, пары cookies, диагностики и подавления эха. */

const { test } = require('node:test');
const assert = require('node:assert/strict');

const {
    normalizeDomain,
    parseDomains,
    cookieKey,
    isCookieForSyncDomain,
    isCookieForSync,
    selectSyncCookiePair,
    hasExpiredCookies,
    describeConnectionFailure,
    pickCookieFields,
    buildCookieUrl,
    buildCookieSetDetails,
    remarkExpectedRemoteChange,
    isExpectedRemoteChange,
} = require('../logic.js');

test('cookie expiry respects seconds, boundary and session semantics', () => {
    const now = 2000;
    assert.equal(hasExpiredCookies([{ name: 'session' }], now), false);
    assert.equal(hasExpiredCookies([{ expirationDate: 2.001 }], now), false);
    for (const expirationDate of [2, 1, null, '3', NaN, Infinity]) {
        assert.equal(hasExpiredCookies([{}, { expirationDate }], now), true);
    }
});

test('normalizeDomain: точка, регистр, пусто', () => {
    assert.equal(normalizeDomain('.reso.ru'), 'reso.ru');
    assert.equal(normalizeDomain('RESO.RU'), 'reso.ru');
    assert.equal(normalizeDomain('Sub.Reso.Ru'), 'sub.reso.ru');
    assert.equal(normalizeDomain(''), '');
    assert.equal(normalizeDomain(undefined), '');
    assert.equal(normalizeDomain(null), '');
});

test('parseDomains: строка через запятую', () => {
    assert.deepEqual(parseDomains('.reso.ru, example.com, '), ['.reso.ru', 'example.com']);
});

test('parseDomains: массив', () => {
    assert.deepEqual(parseDomains([' reso.ru ', '', 'a.ru']), ['reso.ru', 'a.ru']);
});

test('parseDomains: мусор', () => {
    assert.deepEqual(parseDomains(42), []);
    assert.deepEqual(parseDomains(undefined), []);
    assert.deepEqual(parseDomains(''), []);
});

test('cookieKey: одинаковая нормализация домена', () => {
    assert.equal(
        cookieKey({ domain: '.reso.ru', name: 'session', path: '/' }),
        cookieKey({ domain: 'reso.ru', name: 'session', path: '/' })
    );
    assert.equal(cookieKey({ domain: 'RESO.RU', name: 'a' }), 'reso.ru|/|a');
    assert.equal(cookieKey({ domain: 'reso.ru', name: 'a', path: '/x' }), 'reso.ru|/x|a');
});

test('isCookieForSyncDomain: совпадения', () => {
    const domains = ['reso.ru', 'example.com'];

    assert.equal(isCookieForSyncDomain({ domain: 'reso.ru', name: 'a' }, domains), true);
    assert.equal(isCookieForSyncDomain({ domain: 'www.reso.ru', name: 'a' }, domains), true);
    assert.equal(isCookieForSyncDomain({ domain: 'example.com', name: 'a' }, domains), true);
});

test('isCookieForSyncDomain: не матчится evilreso.ru и чужие', () => {
    const domains = ['reso.ru', 'example.com'];

    assert.equal(isCookieForSyncDomain({ domain: 'evilreso.ru', name: 'a' }, domains), false);
    assert.equal(isCookieForSyncDomain({ domain: 'notreso.ru', name: 'a' }, domains), false);
    assert.equal(isCookieForSyncDomain({ domain: '', name: 'a' }, domains), false);
    assert.equal(isCookieForSyncDomain(null, domains), false);
});

test('isCookieForSyncDomain: пустой список доменов', () => {
    assert.equal(isCookieForSyncDomain({ domain: 'reso.ru', name: 'a' }, []), false);
    assert.equal(isCookieForSyncDomain({ domain: 'reso.ru', name: 'a' }, undefined), false);
});

test('isCookieForSync: разрешает только целевые имена на целевых доменах', () => {
    const domains = ['reso.ru'];

    assert.equal(isCookieForSync({ domain: '.reso.ru', name: 'ResoOffice60' }, domains), true);
    assert.equal(isCookieForSync({ domain: 'office.reso.ru', name: 'ASP.NET_SessionId' }, domains), true);
    assert.equal(isCookieForSync({ domain: 'reso.ru', name: 'OtherCookie' }, domains), false);
    assert.equal(isCookieForSync({ domain: 'reso.ru', name: 'resooffice60' }, domains), false);
    assert.equal(isCookieForSync({ domain: 'example.com', name: 'ResoOffice60' }, domains), false);
    assert.equal(isCookieForSync(null, domains), false);
});

test('selectSyncCookiePair: возвращает только полную однозначную пару', () => {
    const domains = ['reso.ru'];
    const asp = { domain: '.reso.ru', path: '/', name: 'ASP.NET_SessionId', value: 'a' };
    const office = { domain: '.reso.ru', path: '/', name: 'ResoOffice60', value: 'b' };

    assert.deepEqual(selectSyncCookiePair([office, asp], domains), [asp, office]);
    assert.deepEqual(selectSyncCookiePair([asp], domains), []);
    assert.deepEqual(selectSyncCookiePair([asp, office, { ...office }], domains), []);
    assert.deepEqual(selectSyncCookiePair([asp, office], ['example.com']), []);
});

test('describeConnectionFailure: распознаёт сервер, запущенный с --no-tls', () => {
    const message = describeConnectionFailure('wss://localhost:52314', null, 426);

    assert.match(message, /отвечает без TLS/);
    assert.match(message, /--no-tls/);
    assert.match(message, /ws:\/\/localhost:52314/);
});

test('describeConnectionFailure: не называет --no-tls ошибкой для ws://', () => {
    const message = describeConnectionFailure('ws://localhost:52314', 426, null);

    assert.match(message, /доступен по HTTP/);
    assert.doesNotMatch(message, /--no-tls/);
});

test('describeConnectionFailure: распознаёт TLS-сервер для адреса ws://', () => {
    const message = describeConnectionFailure('ws://localhost:52314', null, 426);

    assert.match(message, /отвечает с TLS/);
    assert.match(message, /wss:\/\/localhost:52314/);
});

test('pickCookieFields: сохраняет релевантные поля, отбрасывает остальное', () => {
    const cookie = {
        name: 'sid',
        value: '123',
        domain: 'reso.ru',
        path: '/',
        secure: true,
        httpOnly: false,
        sameSite: 'lax',
        expirationDate: 1700000000,
        hostOnly: false,
        storeId: '0',
        session: true,
    };

    const fields = pickCookieFields(cookie);
    assert.deepEqual(fields, {
        name: 'sid',
        value: '123',
        domain: 'reso.ru',
        path: '/',
        secure: true,
        httpOnly: false,
        sameSite: 'lax',
        expirationDate: 1700000000,
        hostOnly: false,
    });
    assert.equal('storeId' in fields, false);
    assert.equal('session' in fields, false);
});

test('pickCookieFields: пропускает неопределённые опциональные поля', () => {
    const fields = pickCookieFields({ name: 'a', value: 'b', domain: 'reso.ru' });
    assert.deepEqual(fields, { name: 'a', value: 'b', domain: 'reso.ru', path: undefined });
    assert.equal('secure' in fields, false);
    assert.equal('sameSite' in fields, false);
});

test('buildCookieUrl: схема и нормализация домена', () => {
    assert.equal(buildCookieUrl({ domain: '.reso.ru', path: '/', secure: true }, 'a.ru'), 'https://reso.ru/');
    assert.equal(buildCookieUrl({ domain: '.RESO.RU', secure: false }, 'a.ru'), 'http://reso.ru/');
    assert.equal(buildCookieUrl({ domain: 'sub.reso.ru', path: '/x' }, 'a.ru'), 'http://sub.reso.ru/x');
    assert.equal(buildCookieUrl({ domain: '', path: '/y' }, 'reso.ru'), 'http://reso.ru/y');
    assert.equal(buildCookieUrl({ secure: true }, 'reso.ru'), 'https://reso.ru/');
});

test('buildCookieSetDetails: сохраняет опциональные поля', () => {
    const details = buildCookieSetDetails({
        name: 'sid', value: 'v', domain: '.reso.ru', path: '/',
        secure: true, httpOnly: true, sameSite: 'lax', expirationDate: 1700000000,
    }, 'fallback.ru');
    assert.deepEqual(details, {
        url: 'https://reso.ru/', name: 'sid', value: 'v',
        domain: '.reso.ru', path: '/',
        secure: true, httpOnly: true, sameSite: 'lax', expirationDate: 1700000000,
    });
});

test('buildCookieSetDetails: отсутствующие поля не включаются', () => {
    const details = buildCookieSetDetails({ name: 'a', value: '1' }, 'fb.ru');
    assert.equal(details.url, 'http://fb.ru/');
    assert.deepEqual(details, { url: 'http://fb.ru/', name: 'a', value: '1' });
});

test('buildCookieSetDetails: host-only cookie не превращается в domain cookie', () => {
    const details = buildCookieSetDetails({
        name: 'a', value: '1', domain: 'office.reso.ru', path: '/', hostOnly: true,
    }, 'reso.ru');

    assert.equal(details.url, 'http://office.reso.ru/');
    assert.equal('domain' in details, false);
});

test('remote change: маркер гасит onChanged даже с другой формой домена', () => {
    const expected = new Map();
    remarkExpectedRemoteChange(expected, { domain: '.reso.ru', name: 's', path: '/' }, 1000);
    assert.equal(isExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's', path: '/' }, 5000, 5000), true);
    assert.equal(isExpectedRemoteChange(expected, { domain: 'RESO.RU', name: 's', path: '/' }, 5000, 5001), false);
});

test('remote change: маркер одноразовый и протухает по TTL', () => {
    const expected = new Map();
    remarkExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 1000);
    assert.equal(isExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 5000, 6000), false);

    remarkExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 7000);
    assert.equal(isExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 5000, 7000), true);
    assert.equal(isExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 5000, 7001), false);
});

test('remote change: другое значение не подавляет локальное изменение', () => {
    const expected = new Map();
    const remote = { domain: 'reso.ru', name: 's', path: '/', value: 'server' };
    const local = { domain: 'reso.ru', name: 's', path: '/', value: 'local' };

    remarkExpectedRemoteChange(expected, remote, 1000);
    assert.equal(isExpectedRemoteChange(expected, local, 5000, 2000), false);
    assert.equal(isExpectedRemoteChange(expected, remote, 5000, 2001), true);
});

test('remote change: overwrite removal и addition подавляются как одна операция', () => {
    const expected = new Map();
    const remote = { domain: 'reso.ru', name: 's', path: '/', value: 'new' };
    const removed = { domain: 'reso.ru', name: 's', path: '/', value: 'old' };

    remarkExpectedRemoteChange(expected, remote, 1000);
    assert.equal(
        isExpectedRemoteChange(expected, removed, 5000, 1100, true, 'overwrite'),
        true,
    );
    assert.equal(isExpectedRemoteChange(expected, remote, 5000, 1101), true);
    assert.equal(isExpectedRemoteChange(expected, remote, 5000, 1102), false);
});

test('remote change: явное удаление с другим значением не подавляется', () => {
    const expected = new Map();
    const remote = { domain: 'reso.ru', name: 's', path: '/', value: 'new' };
    const removed = { domain: 'reso.ru', name: 's', path: '/', value: 'old' };

    remarkExpectedRemoteChange(expected, remote, 1000);
    assert.equal(
        isExpectedRemoteChange(expected, removed, 5000, 1100, true, 'explicit'),
        false,
    );
});

test('remote change: явное удаление ожидаемого значения тоже не подавляется', () => {
    const expected = new Map();
    const cookie = { domain: 'reso.ru', name: 's', path: '/', value: 'same' };

    remarkExpectedRemoteChange(expected, cookie, 1000);
    assert.equal(
        isExpectedRemoteChange(expected, cookie, 5000, 1100, true, 'explicit'),
        false,
    );
});

test('cookieKey: разные path и name дают разные ключи', () => {
    assert.notEqual(
        cookieKey({ domain: 'reso.ru', name: 's', path: '/' }),
        cookieKey({ domain: 'reso.ru', name: 's', path: '/x' })
    );
    assert.notEqual(
        cookieKey({ domain: 'reso.ru', name: 's', path: '/' }),
        cookieKey({ domain: 'reso.ru', name: 'other', path: '/' })
    );
    // отсутствие path → дефолтный '/', один и тот же ключ
    assert.equal(
        cookieKey({ domain: 'reso.ru', name: 's' }),
        cookieKey({ domain: 'reso.ru', name: 's', path: '/' })
    );
    // host-only (без domain): пустой домен не коллизирует с реальным
    assert.notEqual(
        cookieKey({ name: 's', path: '/' }),
        cookieKey({ domain: 'reso.ru', name: 's', path: '/' })
    );
});

test('isCookieForSyncDomain: целевой домен с точкой (.reso.ru)', () => {
    const domains = ['.reso.ru'];

    assert.equal(isCookieForSyncDomain({ domain: '.reso.ru', name: 'a' }, domains), true);
    assert.equal(isCookieForSyncDomain({ domain: 'reso.ru', name: 'a' }, domains), true);
    assert.equal(isCookieForSyncDomain({ domain: 'www.reso.ru', name: 'a' }, domains), true);
    assert.equal(isCookieForSyncDomain({ domain: 'sub.reso.ru', name: 'a' }, domains), true);
    // злой сабстринг-матчинг не должен сработать
    assert.equal(isCookieForSyncDomain({ domain: 'evilreso.ru', name: 'a' }, domains), false);
    assert.equal(isCookieForSyncDomain({ domain: 'notreso.ru', name: 'a' }, domains), false);
});

test('remote change: границы TTL (now === at и ttl = 0)', () => {
    const expected = new Map();
    remarkExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 1000);
    // ровно в момент пометки маркер активен (0 < ttlMs)
    assert.equal(isExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 5000, 1000), true);

    // ttl=0: даже при now === at маркер уже мёртв
    remarkExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 2000);
    assert.equal(isExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 0, 2000), false);
});

test('remote change: повторный remark освежает TTL, но маркер остаётся одноразовым', () => {
    const expected = new Map();
    remarkExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 1000);
    // другой регистр — тот же самый ключ
    remarkExpectedRemoteChange(expected, { domain: 'RESO.RU', name: 's' }, 3000);

    // старый маркер (1000) истёк, свежий (3000) живёт
    assert.equal(isExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 5000, 3500), true);
    // удалён после первого потребления
    assert.equal(isExpectedRemoteChange(expected, { domain: 'reso.ru', name: 's' }, 5000, 3501), false);
});

test('remote change: markers in regular and private stores are independent', () => {
    const expected = new Map();
    const regular = { domain: '.reso.ru', path: '/', name: 's', value: 'same', storeId: '0' };
    const privateCookie = { ...regular, storeId: '1' };
    remarkExpectedRemoteChange(expected, regular, 1000);
    assert.equal(isExpectedRemoteChange(expected, privateCookie, 5000, 1001), false);
    remarkExpectedRemoteChange(expected, privateCookie, 1000);
    assert.equal(isExpectedRemoteChange(expected, regular, 5000, 1001), true);
    assert.equal(isExpectedRemoteChange(expected, privateCookie, 5000, 1001), true);
});

test('cookie store IDs are selected locally and never serialized in the protocol', () => {
    const cookie = { domain: '.reso.ru', path: '/', name: 's', value: 'value', storeId: 'remote-id' };
    assert.equal('storeId' in pickCookieFields(cookie), false);
    assert.equal('storeId' in buildCookieSetDetails(cookie, 'reso.ru'), false);
    assert.equal(buildCookieSetDetails(cookie, 'reso.ru', 'local-private').storeId, 'local-private');
});
