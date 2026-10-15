/**
 * @file Чистые функции настроек, cookies и защиты от циклов синхронизации.
 * В браузере доступны как глобальные функции через importScripts или script;
 * в Node.js экспортируются через module.exports. Браузерные API не вызываются.
 */

/**
 * @typedef {Object} SyncSettings
 * @property {string} account Имя серверного аккаунта.
 * @property {string} serverUrl Адрес WebSocket-сервера.
 * @property {string[]} cookieDomains Разрешённые домены cookies.
 * @property {boolean} enabled Запрошенное состояние синхронизации.
 */

const SYNC_COOKIE_NAMES = ['ASP.NET_SessionId', 'ResoOffice60'];

/**
 * Удаляет пробелы по краям ввода и дополняет настройки значениями по умолчанию.
 * @param {Object} [settings={}] Текущие или старые настройки с cookieDomain.
 * @returns {SyncSettings} Новый объект; валидность URL и аккаунта не проверяется.
 */
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

/**
 * Нормализует настройки, проверяет ws/wss без фрагмента и аккаунт при включении.
 * @param {Object} settings Настройки одного cookie store.
 * @returns {SyncSettings} Нормализованные настройки.
 * @throws {Error} При неверном URL или пустом аккаунте включённого контекста.
 */
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

/** Приводит домен к нижнему регистру и удаляет одну ведущую точку. */
function normalizeDomain(domain) {
    return String(domain || '').replace(/^\./, '').toLowerCase();
}

/**
 * Разбирает список или строку доменов через запятую, удаляя пробелы и пустые элементы.
 * @param {string|string[]|undefined} value Исходное значение настройки.
 * @returns {string[]} Новый список без проверки синтаксиса и удаления дубликатов.
 */
function parseDomains(value) {
    if (Array.isArray(value)) {
        return value.map(String).map(s => s.trim()).filter(Boolean);
    }
    if (typeof value === 'string') {
        return value.split(',').map(s => s.trim()).filter(Boolean);
    }
    return [];
}

/** Возвращает ключ domain/path/name внутри одного store; ведущая точка незначима. */
function cookieKey(cookie) {
    return `${normalizeDomain(cookie.domain)}|${cookie.path || '/'}|${cookie.name}`;
}

/** Дополняет ключ cookie локальным storeId для изоляции маркеров изменений. */
function cookieStoreKey(cookie) {
    return `${cookie.storeId || ''}|${cookieKey(cookie)}`;
}

/**
 * Проверяет точное совпадение домена или его поддомен с границей по точке.
 * Например, evilreso.ru не подходит под reso.ru.
 * @param {Object} cookie Cookie с полем domain.
 * @param {string[]} domains Настроенные целевые домены.
 * @returns {boolean} Принадлежность хотя бы одному целевому домену.
 */
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

/** Проверяет разрешённое имя cookie и принадлежность настроенному домену. */
function isCookieForSync(cookie, domains) {
    return Boolean(
        cookie
        && SYNC_COOKIE_NAMES.includes(cookie.name)
        && isCookieForSyncDomain(cookie, domains)
    );
}

/**
 * Выбирает ровно по одной cookie каждого разрешённого имени в стабильном порядке.
 * @param {Object[]} cookies Cookies одного store; посторонние имена игнорируются.
 * @param {string[]} domains Целевые домены.
 * @returns {Object[]} Ссылки на исходные cookies либо [] при неполной/неоднозначной паре.
 */
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

/**
 * Формирует подсказку по результатам HTTP/HTTPS-диагностики WebSocket-адреса.
 * @param {string} url Настроенный ws:// или wss:// URL.
 * @param {number|null} primaryStatus HTTP-код при соответствующей схеме, null при ошибке.
 * @param {number|null} alternateStatus HTTP-код при противоположной схеме.
 * @param {boolean} [timedOut=false] Был ли таймаут хотя бы одной пробы.
 * @returns {string} Сообщение для пользователя, без утверждения точной причины TLS-ошибки.
 */
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

/**
 * Копирует переносимые поля cookie, исключая локальный storeId.
 * Отсутствующая expirationDate остаётся отсутствующей для сохранения session-семантики.
 * @returns {Object} Новый объект для серверной нагрузки.
 */
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

/** Строит URL установки cookie по secure, domain (либо fallbackDomain) и path. */
function buildCookieUrl(cookie, fallbackDomain) {
    const domain = normalizeDomain(cookie.domain || fallbackDomain);
    const scheme = cookie.secure ? 'https' : 'http';
    return `${scheme}://${domain}${cookie.path || '/'}`;
}

/**
 * Готовит аргумент cookies.set, сохраняя hostOnly и время жизни cookie.
 * @param {Object} cookie Переносимые поля удалённой cookie.
 * @param {string} fallbackDomain Домен при отсутствии cookie.domain.
 * @param {string} [storeId] Локальный целевой store; не берётся из серверной нагрузки.
 * @returns {Object} Данные для браузерного API, без самого вызова API.
 */
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

/**
 * Помечает ожидаемую локальную установку удалённой cookie перед cookies.set.
 * @param {Map} expected Изменяемая карта маркеров контекста.
 * @param {Object} cookie Cookie с локальным storeId и ожидаемым значением.
 * @param {number} [now=Date.now()] Время в миллисекундах для проверки TTL.
 */
function remarkExpectedRemoteChange(expected, cookie, now = Date.now()) {
    expected.set(cookieStoreKey(cookie), {
        at: now,
        value: String(cookie.value !== undefined ? cookie.value : ''),
    });
}

/**
 * Проверяет событие onChanged на соответствие ожидаемой удалённой записи.
 * Удаление при overwrite подавляется без расходования маркера; совпавшая
 * установка расходует его. Истёкшие маркеры удаляются, иные удаления не подавляются.
 * @param {Map} expected Изменяемая карта маркеров.
 * @param {Object} cookie Cookie события с локальным storeId.
 * @param {number} ttlMs Время жизни маркера в миллисекундах.
 * @param {number} [now=Date.now()] Текущее время в миллисекундах.
 * @param {boolean} [removed=false] Признак удаления из события.
 * @param {string} [cause=''] Причина изменения из события.
 * @returns {boolean} Нужно ли подавить обратную отправку на сервер.
 */
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
