// Чистые функции, общие для background и popup.
// В расширении подключаются как обычные глобальные функции
// (importScripts / <script>), в Node.js для тестов — как модуль.

const SYNC_COOKIE_NAMES = ['ASP.NET_SessionId', 'ResoOffice60'];

function normalizeSyncSettings(settings = {}) {
    const domains = parseDomains(settings.cookieDomains ?? settings.cookieDomain);
    return {
        account: typeof settings.account === 'string' ? settings.account.trim() : '',
        serverUrl: typeof settings.serverUrl === 'string' && settings.serverUrl.trim()
            ? settings.serverUrl.trim() : 'ws://mnas:52314',
        cookieDomains: domains.length ? domains : ['.reso.ru'],
        enabled: settings.enabled === true,
    };
}

function validateSyncSettings(settings) {
    const result = normalizeSyncSettings(settings);
    let url;
    try {
        url = new URL(result.serverUrl);
    } catch (error) {
        throw new Error('Некорректный адрес сервера');
    }
    if (!['ws:', 'wss:'].includes(url.protocol) || url.hash) {
        throw new Error('Укажите адрес ws:// или wss:// без фрагмента #');
    }
    if (result.enabled && !result.account) {
        throw new Error('Укажите аккаунт для этого контекста');
    }
    return result;
}

function normalizeDomain(domain) {
    return String(domain || '').replace(/^\./, '').toLowerCase();
}

function parseDomains(value) {
    if (Array.isArray(value)) {
        return value.map(String).map(s => s.trim()).filter(Boolean);
    }
    if (typeof value === 'string') {
        return value.split(',').map(s => s.trim()).filter(Boolean);
    }
    return [];
}

function cookieKey(cookie) {
    return `${normalizeDomain(cookie.domain)}|${cookie.path || '/'}|${cookie.name}`;
}

function cookieStoreKey(cookie) {
    return `${cookie.storeId || ''}|${cookieKey(cookie)}`;
}

// Домен куки принадлежит одному из целевых доменов:
// domain === target || domain.endsWith('.' + target).
// Не используем substring-матчинг: evilreso.ru не должен подходить под reso.ru.
function isCookieForSyncDomain(cookie, domains) {
    const domain = normalizeDomain(cookie && cookie.domain);
    if (!domain) {
        return false;
    }
    return (domains || []).some((raw) => {
        const target = normalizeDomain(raw);
        return domain === target || domain.endsWith('.' + target);
    });
}

function isCookieForSync(cookie, domains) {
    return Boolean(
        cookie
        && SYNC_COOKIE_NAMES.includes(cookie.name)
        && isCookieForSyncDomain(cookie, domains)
    );
}

function selectSyncCookiePair(cookies, domains) {
    if (!Array.isArray(cookies)) {
        return [];
    }
    const selected = [];
    for (const name of SYNC_COOKIE_NAMES) {
        const matches = cookies.filter(
            cookie => cookie && cookie.name === name && isCookieForSyncDomain(cookie, domains)
        );
        if (matches.length !== 1) {
            return [];
        }
        selected.push(matches[0]);
    }
    return selected;
}

function describeConnectionFailure(url, primaryStatus, alternateStatus, timedOut = false) {
    let wsUrl;
    try {
        wsUrl = new URL(url);
    } catch (e) {
        return `Некорректный адрес сервера: ${url}`;
    }

    const usesTls = wsUrl.protocol === 'wss:';
    if (wsUrl.protocol !== 'ws:' && !usesTls) {
        return `Некорректный адрес сервера: ${url}`;
    }

    if (primaryStatus !== null) {
        const httpProtocol = usesTls ? 'HTTPS' : 'HTTP';
        return `Узел ${wsUrl.host} доступен по ${httpProtocol} (код ${primaryStatus}), но WebSocket-соединение ${wsUrl.protocol}// не установлено. Проверьте адрес, порт и настройки прокси`;
    }

    if (alternateStatus !== null) {
        if (usesTls) {
            return `Сервер ${wsUrl.host} отвечает без TLS. Если он запущен с --no-tls, укажите в настройках ws://${wsUrl.host}; иначе включите TLS на сервере`;
        }
        return `Сервер ${wsUrl.host} отвечает с TLS. Укажите в настройках wss://${wsUrl.host} или запустите сервер с --no-tls для адреса ws://${wsUrl.host}`;
    }

    if (timedOut) {
        return `${wsUrl.host} не отвечает (таймаут). Проверьте, запущен ли сервер, а также адрес, порт, сеть и файрвол`;
    }

    if (usesTls) {
        return `Не удалось установить соединение с ${url}. Проверьте запуск сервера, сеть и TLS-сертификат; браузер не сообщает точную причину ошибки`;
    }
    return `Не удалось установить соединение с ${url}. Проверьте, что сервер запущен с --no-tls, а адрес, порт и сеть доступны`;
}

function pickCookieFields(cookie) {
    const fields = {
        name: cookie.name,
        value: cookie.value,
        domain: cookie.domain,
        path: cookie.path
    };

    if (cookie.secure !== undefined) {
        fields.secure = cookie.secure;
    }
    if (cookie.httpOnly !== undefined) {
        fields.httpOnly = cookie.httpOnly;
    }
    if (cookie.sameSite !== undefined) {
        fields.sameSite = cookie.sameSite;
    }
    if (cookie.expirationDate !== undefined) {
        fields.expirationDate = cookie.expirationDate;
    }
    if (cookie.hostOnly !== undefined) {
        fields.hostOnly = cookie.hostOnly;
    }
    return fields;
}

// URL, на который ставится удалённая кука.
function buildCookieUrl(cookie, fallbackDomain) {
    const domain = normalizeDomain(cookie.domain || fallbackDomain);
    const scheme = cookie.secure ? 'https' : 'http';
    return `${scheme}://${domain}${cookie.path || '/'}`;
}

// Детали вызова browser.cookies.set (без зависимости от браузерного API).
function buildCookieSetDetails(cookie, fallbackDomain, storeId) {
    const details = {
        url: buildCookieUrl(cookie, fallbackDomain),
        name: cookie.name,
        value: String(cookie.value !== undefined ? cookie.value : '')
    };

    if (cookie.domain && cookie.hostOnly !== true) {
        details.domain = cookie.domain;
    }
    if (cookie.path) {
        details.path = cookie.path;
    }
    if (cookie.secure !== undefined) {
        details.secure = cookie.secure;
    }
    if (cookie.httpOnly !== undefined) {
        details.httpOnly = cookie.httpOnly;
    }
    if (cookie.sameSite) {
        details.sameSite = cookie.sameSite;
    }
    if (cookie.expirationDate !== undefined) {
        details.expirationDate = cookie.expirationDate;
    }
    // Store IDs are local browser state, never taken from the server payload.
    if (storeId !== undefined) {
        details.storeId = storeId;
    }
    return details;
}

// Защита от циклов синхронизации: помечаем куки, которые собираемся
// выставлять локально; onChanged для них не должен вызывать повторный set.
// Ключ нормализуется через cookieKey, поэтому .reso.ru и reso.ru совпадают.
function remarkExpectedRemoteChange(expected, cookie, now = Date.now()) {
    expected.set(cookieStoreKey(cookie), {
        at: now,
        value: String(cookie.value !== undefined ? cookie.value : ''),
    });
}

function isExpectedRemoteChange(
    expected,
    cookie,
    ttlMs,
    now = Date.now(),
    removed = false,
    cause = '',
) {
    const key = cookieStoreKey(cookie);
    const marker = expected.get(key);
    if (!marker) {
        return false;
    }
    if (now - marker.at >= ttlMs) {
        expected.delete(key);
        return false;
    }
    if (removed && (cause === 'overwrite' || cause === 'expired_overwrite')) {
        return true;
    }
    if (removed) {
        return false;
    }
    const value = String(cookie.value !== undefined ? cookie.value : '');
    if (marker.value === value) {
        expected.delete(key);
        return true;
    }
    return false;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        normalizeSyncSettings,
        validateSyncSettings,
        normalizeDomain,
        parseDomains,
        cookieKey,
        cookieStoreKey,
        isCookieForSyncDomain,
        isCookieForSync,
        selectSyncCookiePair,
        describeConnectionFailure,
        pickCookieFields,
        buildCookieUrl,
        buildCookieSetDetails,
        remarkExpectedRemoteChange,
        isExpectedRemoteChange,
    };
}
