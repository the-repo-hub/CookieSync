// Чистые функции, общие для background и popup.
// В расширении подключаются как обычные глобальные функции
// (importScripts / <script>), в Node.js для тестов — как модуль.

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
function buildCookieSetDetails(cookie, fallbackDomain) {
    const details = {
        url: buildCookieUrl(cookie, fallbackDomain),
        name: cookie.name,
        value: String(cookie.value !== undefined ? cookie.value : '')
    };

    if (cookie.domain) {
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
    return details;
}

// Защита от циклов синхронизации: помечаем куки, которые собираемся
// выставлять локально; onChanged для них не должен вызывать повторный set.
// Ключ нормализуется через cookieKey, поэтому .reso.ru и reso.ru совпадают.
function remarkExpectedRemoteChange(expected, cookie, now = Date.now()) {
    expected.set(cookieKey(cookie), now);
}

function isExpectedRemoteChange(expected, cookie, ttlMs, now = Date.now()) {
    const key = cookieKey(cookie);
    const at = expected.get(key);
    if (at !== undefined && now - at < ttlMs) {
        expected.delete(key);
        return true;
    }
    return false;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        normalizeDomain,
        parseDomains,
        cookieKey,
        isCookieForSyncDomain,
        pickCookieFields,
        buildCookieUrl,
        buildCookieSetDetails,
        remarkExpectedRemoteChange,
        isExpectedRemoteChange,
    };
}