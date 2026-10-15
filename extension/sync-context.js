/**
 * @file Синхронизация одного cookie store: сокет, UUID, cookies и повторный вход.
 */

/**
 * Независимый клиент одного браузерного хранилища cookies.
 * Очереди, ревизии, таймеры и маркеры не разделяются между экземплярами.
 * generation обесценивает async-операции после смены соединения или настроек.
 */
class CookieSyncContext {
    /**
     * @param {Object} store Локальный store с id, incognito и живыми tabIds.
     * @param {Object} settings Исходные настройки; включённые запускают соединение.
     * @param {Function} notify Синхронное уведомление менеджера об изменении статуса.
     * @param {string} [contextId] Идентификатор текущего времени жизни контекста.
     * @param {Function} [recoveryChanged] Async-сохранение снимка входа в storage.session.
     */
    constructor(store, settings, notify, contextId = crypto.randomUUID(), recoveryChanged = async () => {}) {
        this.storeId = store.id;
        this.incognito = store.incognito;
        this.tabIds = new Set(store.tabIds);
        this.contextId = contextId;
        this.settings = normalizeSyncSettings();
        this.notify = notify;
        this.recoveryChanged = recoveryChanged;
        this.authStates = new Map();
        this.recovery = null;
        this.alive = true;
        this.socket = null;
        this.registered = false;
        this.generation = 0;
        this.pending = new Map();
        this.expectedChanges = new Map();
        this.applyQueue = Promise.resolve();
        this.latestPayload = [];
        this.latestRevision = -1;
        this.initialPending = false;
        this.reconnectTimer = null;
        this.syncTimer = null;
        this.remoteRetryTimer = null;
        this.phase = 'idle';
        this.detail = '';
        this.error = '';
        this.configure(settings);
    }

    /** Возвращает UI-снимок статуса с копией настроек и списка доменов. */
    status() {
        return {
            contextId: this.contextId, storeId: this.storeId, incognito: this.incognito,
            settings: { ...this.settings, cookieDomains: [...this.settings.cookieDomains] },
            connected: this.socket?.readyState === WebSocket.OPEN,
            phase: this.phase, detail: this.detail, error: this.error,
        };
    }

    /** Обновляет фазу и сообщение ошибки живого контекста, уведомляя менеджер. */
    setPhase(phase, detail = '') {
        if (!this.alive) return;
        this.phase = phase;
        this.detail = detail;
        if (phase === 'error') this.error = detail;
        else if (phase === 'online' || phase === 'idle') this.error = '';
        this.notify(this);
    }

    /** Применяет изменившиеся настройки через остановку и, при включении, подключение. */
    configure(settings) {
        const normalized = normalizeSyncSettings(settings);
        if (!this.alive || JSON.stringify(normalized) === JSON.stringify(this.settings)) return;
        this.stop();
        this.settings = normalized;
        if (normalized.enabled && normalized.account) this.connect();
    }

    /**
     * Закрывает сокет, отменяет таймеры и отклоняет ожидающие UUID-запросы.
     * @param {boolean} [preserveRecovery=false] При reconnect сохраняет последнюю
     * известную ревизию и попытку входа с новым объектом владения inFlight.
     */
    stop(preserveRecovery = false) {
        this.generation += 1;
        this.registered = false;
        this.initialPending = false;
        for (const timer of [this.reconnectTimer, this.syncTimer, this.remoteRetryTimer]) clearTimeout(timer);
        this.reconnectTimer = this.syncTimer = this.remoteRetryTimer = null;
        for (const pending of this.pending.values()) {
            clearTimeout(pending.timer);
            pending.reject(new Error('Контекст отключён'));
        }
        this.pending.clear();
        const connection = this.socket;
        this.socket = null;
        if (connection) connection.close();
        this.latestPayload = [];
        this.expectedChanges.clear();
        if (!preserveRecovery) {
            this.latestRevision = -1;
            this.authStates.clear();
            this.clearRecovery().catch(error => console.warn('[CookieSync] Could not clear login recovery:', error));
        } else if (this.recovery) {
            // A suspended task still owns the old object. Its finally must not
            // unlock a refresh started by the replacement connection.
            this.recovery = { ...this.recovery, inFlight: false };
        }
        this.setPhase('idle');
    }

    /**
     * Завершает время жизни контекста и очищает его настройки и вкладки.
     * @returns {Promise} Завершение очереди cookies перед повторным использованием storeId.
     */
    dispose() {
        this.stop();
        this.alive = false;
        this.settings = normalizeSyncSettings();
        this.tabIds.clear();
        return this.applyQueue;
    }

    /** Проверяет, что async-операция всё ещё относится к активному открытому сокету. */
    isCurrent(connection, generation) {
        return this.alive && this.settings.enabled && this.socket === connection
            && this.generation === generation && connection?.readyState === WebSocket.OPEN;
    }

    /** Находит живой store; приватный дополнительно должен содержать известную вкладку. */
    async currentStore() {
        const stores = await browser.cookies.getAllCookieStores();
        return stores.find(store => store.id === this.storeId
            && (!this.incognito || store.tabIds.some(id => this.tabIds.has(id))));
    }

    /** Восстанавливает соединение включённого контекста при пробуждении alarm. */
    keepAlive() {
        if (this.alive && this.settings.enabled) this.connect();
    }

    /** Планирует единственный reconnect через 5 секунд для включённого контекста. */
    scheduleReconnect() {
        if (!this.alive || !this.settings.enabled || this.reconnectTimer !== null) return;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.connect();
        }, 5000);
    }

    /**
     * Открывает один WebSocket и регистрирует аккаунт после события open.
     * Повторный вызов при OPEN/CONNECTING ничего не создаёт; обработчики событий
     * проверяют принадлежность сокета текущему поколению контекста.
     */
    connect() {
        if (!this.alive || !this.settings.enabled || !this.settings.account
            || this.socket?.readyState === WebSocket.OPEN || this.socket?.readyState === WebSocket.CONNECTING) return;
        try {
            validateSyncSettings(this.settings);
        } catch (error) {
            this.setPhase('error', error.message);
            return;
        }
        const generation = ++this.generation;
        this.latestPayload = [];
        // A login may start while disconnected or while register is pending.
        // Its fence must use the last known revision of this same account.
        this.setPhase('connecting', this.settings.serverUrl);
        try {
            const connection = new WebSocket(this.settings.serverUrl);
            this.socket = connection;
            connection.addEventListener('open', async () => {
                if (!this.isCurrent(connection, generation)) { connection.close(); return; }
                clearTimeout(this.reconnectTimer);
                this.reconnectTimer = null;
                this.setPhase('registering', this.settings.account);
                try {
                    const response = await this.sendCommand('register', {});
                    if (!this.isCurrent(connection, generation)) return;
                    this.registered = true;
                    this.initialPending = Array.isArray(response.payload)
                        && (response.payload.length === 0 || hasExpiredCookies(
                            selectSyncCookiePair(response.payload, this.settings.cookieDomains),
                        ))
                        && !this.latestPayload.length;
                    this.setPhase('online', this.initialPending ? 'Проверка локальных cookies' : '');
                    if (this.initialPending || this.recovery?.ready) this.scheduleSync(!this.recovery?.ready);
                    this.watchAuthentication(connection, generation).catch(error => {
                        console.warn('[CookieSync] Could not start login observation:', error);
                    });
                } catch (error) {
                    if (!this.isCurrent(connection, generation)) return;
                    this.setPhase('error', `Регистрация: ${error.message}`);
                    connection.close();
                }
            });
            connection.addEventListener('message', event => {
                if (this.isCurrent(connection, generation)) this.handleMessage(event.data, connection);
            });
            connection.addEventListener('close', () => {
                if (this.socket !== connection) return;
                this.stop(true);
                if (this.alive && this.settings.enabled) {
                    this.setPhase('disconnected', 'Соединение потеряно');
                    this.scheduleReconnect();
                }
            });
            connection.addEventListener('error', () => {
                if (this.socket !== connection) return;
                const url = this.settings.serverUrl;
                this.setPhase('error', `Не удалось подключиться к ${url}`);
                this.diagnoseConnection(url).then(detail => {
                    if (this.socket === connection && this.generation === generation && this.phase === 'error') {
                        this.setPhase('error', detail);
                    }
                }).catch(error => console.warn('[CookieSync] Connection diagnosis failed:', error));
            });
        } catch (error) {
            this.socket = null;
            this.setPhase('error', error.message);
            this.scheduleReconnect();
        }
    }

    /**
     * Отправляет запрос с новым UUID и таймаутом ответа 10 секунд.
     * @param {string} command Команда серверного протокола.
     * @param {Object|Object[]} payload Нагрузка команды.
     * @param {Object|null} [recovery=null] Попытка refresh с закреплённой expectedRevision.
     * @returns {Promise<Object>} Только коррелированный ответ после обработки cookies;
     * сетевые ошибки, отказ сервера и таймаут отклоняют Promise.
     */
    sendCommand(command, payload, recovery = null) {
        const connection = this.socket;
        if (!this.alive || !this.settings.enabled || connection?.readyState !== WebSocket.OPEN) {
            return Promise.reject(new Error('Socket not connected'));
        }
        const uuid = crypto.randomUUID();
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
                this.pending.delete(uuid);
                reject(new Error('Request timeout'));
            }, 10000);
            this.pending.set(uuid, { resolve, reject, timer, connection, command, recovery });
            try {
                connection.send(JSON.stringify({
                    command, account: this.settings.account, uuid, payload,
                    ...(recovery ? { expected_revision: recovery.expectedRevision } : {}),
                }));
            } catch (error) {
                clearTimeout(timer);
                this.pending.delete(uuid);
                reject(error);
            }
        });
    }

    /** Пробует HTTP/HTTPS серверного узла и возвращает подсказку о сбое соединения. */
    async diagnoseConnection(url) {
        const parsed = new URL(url);
        const primaryScheme = parsed.protocol === 'wss:' ? 'https' : 'http';
        const alternateScheme = primaryScheme === 'https' ? 'http' : 'https';
        const primary = await this.probeEndpoint(`${primaryScheme}://${parsed.host}/`);
        const alternate = primary.status === null
            ? await this.probeEndpoint(`${alternateScheme}://${parsed.host}/`)
            : { status: null, timedOut: false };
        return describeConnectionFailure(url, primary.status, alternate.status, primary.timedOut || alternate.timedOut);
    }

    /**
     * Диагностирует доступность узла без credentials с таймаутом 4 секунды.
     * @returns {Promise<{status: number|null, timedOut: boolean}>} HTTP-код или ошибка.
     */
    async probeEndpoint(url) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 4000);
        try {
            const response = await fetch(url, {
                cache: 'no-store', credentials: 'omit', redirect: 'manual', signal: controller.signal,
            });
            return { status: response.status, timedOut: false };
        } catch (error) {
            return { status: null, timedOut: error?.name === 'AbortError' };
        } finally {
            clearTimeout(timer);
        }
    }

    /**
     * Разделяет push set и ответы по UUID, учитывая сокет ожидающего запроса.
     * Поздний ответ без ожидателя может обновить cookies, но не завершает другой запрос.
     */
    handleMessage(message, connection) {
        let response;
        try { response = JSON.parse(message); }
        catch (error) { console.warn('[CookieSync] Invalid server JSON:', error); return; }
        if (!response || typeof response !== 'object') return;
        if (response.command === 'set') {
            this.applyCookies(response.payload, response.revision);
            return;
        }
        const pending = this.pending.get(response.uuid);
        if (pending && pending.connection === connection) {
            const generation = this.generation;
            clearTimeout(pending.timer);
            this.pending.delete(response.uuid);
            if (!response.result) {
                pending.reject(new Error(response.message || 'Request failed'));
                return;
            }
            const applyResponse = async () => {
                if (pending.command === 'refresh' && this.recovery === pending.recovery
                    && typeof response.accepted === 'boolean' && Number.isInteger(response.revision)) {
                    await this.clearRecovery();
                }
                if (!this.isCurrent(connection, generation)) return false;
                return this.applyCookies(response.payload, response.revision);
            };
            applyResponse().then(
                applied => pending.resolve({ ...response, applied }), pending.reject,
            );
        } else if (response.uuid && Array.isArray(response.payload) && Number.isInteger(response.revision)) {
            this.applyCookies(response.payload, response.revision);
        }
    }

    /**
     * Ставит применение серверной пары в последовательную очередь этого store.
     * Более старые ревизии игнорируются; пара закреплённой ревизии удерживается
     * на время входа, а более новая завершает recovery. Ошибка записи планирует повтор.
     * @param {Object[]} payload Серверные cookies без доверия к их storeId.
     * @param {number} revision Серверная ревизия; учитывается только целое значение.
     * @returns {Promise<boolean>} true при применении или уже известной более новой
     * ревизии; false при пустой паре, удержании, отмене либо ошибке записи.
     */
    applyCookies(payload, revision) {
        const cookies = selectSyncCookiePair(payload, this.settings.cookieDomains);
        if (!this.alive || !this.settings.enabled) return Promise.resolve(false);
        if (cookies.length && hasExpiredCookies(cookies)) {
            console.warn('[CookieSync] Ignoring expired server cookies');
            return this.applyCookies([], revision);
        }
        if (!cookies.length) {
            if (Array.isArray(payload) && !payload.length && Number.isInteger(revision)
                && revision >= this.latestRevision) {
                this.latestRevision = revision;
                this.latestPayload = [];
                this.initialPending = true;
                clearTimeout(this.remoteRetryTimer);
                this.remoteRetryTimer = null;
                if (this.recovery && revision > this.recovery.expectedRevision) {
                    return this.clearRecovery().then(() => false);
                }
            }
            return Promise.resolve(false);
        }
        if (Number.isInteger(revision)) {
            if (revision < this.latestRevision) return Promise.resolve(true);
            this.latestRevision = revision;
        }
        this.latestPayload = cookies.map(pickCookieFields);
        this.initialPending = false;
        let recoverySaved = Promise.resolve();
        const resolvedLogin = this.recovery && Number.isInteger(revision) && revision > this.recovery.expectedRevision;
        if (resolvedLogin) {
            // A newer revision wins. Do not rebase an old login attempt onto it.
            recoverySaved = this.clearRecovery();
        }
        const heldForLogin = () => this.recovery
            && (!Number.isInteger(revision) || revision <= this.recovery.expectedRevision);
        if (heldForLogin()) return Promise.resolve(false);
        clearTimeout(this.remoteRetryTimer);
        this.remoteRetryTimer = null;
        const connection = this.socket;
        const generation = this.generation;
        const current = () => this.isCurrent(connection, generation)
            && (!Number.isInteger(revision) || revision >= this.latestRevision) && !heldForLogin();
        const apply = async () => {
            if (!current()) return false;
            try {
                await recoverySaved;
                if (!current()) return false;
                const store = await this.currentStore();
                if (!store || !current()) return false;
                for (const cookie of cookies) {
                    if (!current()) return false;
                    // A valid pair can expire while queued or during an API await.
                    if (hasExpiredCookies(cookies)) return this.applyCookies([], revision);
                    remarkExpectedRemoteChange(this.expectedChanges, { ...cookie, storeId: this.storeId });
                    const result = await browser.cookies.set(buildCookieSetDetails(
                        cookie, this.settings.cookieDomains[0], this.storeId,
                    ));
                    if (!current()) return false;
                    if (!result || result.storeId !== this.storeId || result.value !== cookie.value
                        || normalizeDomain(result.domain) !== normalizeDomain(cookie.domain)
                        || result.path !== (cookie.path || '/')
                        || (cookie.hostOnly !== undefined && result.hostOnly !== cookie.hostOnly)) {
                        throw new Error('Browser did not persist the expected cookie');
                    }
                }
                if (resolvedLogin && this.registered) this.setPhase('online');
                return true;
            } catch (error) {
                console.warn(`[CookieSync] Cookie application failed for ${this.storeId}:`, error);
                if (current() && this.remoteRetryTimer === null) {
                    this.remoteRetryTimer = setTimeout(() => {
                        this.remoteRetryTimer = null;
                        if (current()) this.applyCookies(cookies, revision);
                    }, 1000);
                }
                return false;
            }
        };
        this.applyQueue = this.applyQueue.catch(error => {
            console.warn('[CookieSync] Previous cookie operation failed:', error);
        }).then(apply);
        return this.applyQueue;
    }

    /** Возвращает сериализуемые наблюдения входа для storage.session без inFlight. */
    snapshotRecovery() {
        if (!this.recovery && !this.authStates.size) return null;
        return {
            account: this.settings.account, serverUrl: this.settings.serverUrl, contextId: this.contextId,
            cookieDomains: [...this.settings.cookieDomains],
            ...(this.recovery ? { tabId: this.recovery.tabId,
                expectedRevision: this.recovery.expectedRevision, ready: this.recovery.ready } : {}),
            observations: [...this.authStates].map(([tabId, state]) => ({ ...state, tabId, retired: [...state.retired] })),
        };
    }

    /** Восстанавливает fence ревизии только для совпавших настроек и живых вкладок. */
    restoreRecovery(record) {
        if (!record || !this.settings.enabled || record.account !== this.settings.account
            || record.serverUrl !== this.settings.serverUrl
            || JSON.stringify(record.cookieDomains) !== JSON.stringify(this.settings.cookieDomains)
            || (this.incognito && record.contextId !== this.contextId)) return;
        for (const state of record.observations || []) {
            if (this.tabIds.has(state.tabId)) {
                this.authStates.set(state.tabId, { ...state, retired: new Set(state.retired || []) });
            }
        }
        if (this.tabIds.has(record.tabId) && Number.isInteger(record.expectedRevision) && record.expectedRevision >= 0) {
            this.recovery = { tabId: record.tabId, expectedRevision: record.expectedRevision,
                ready: record.ready === true, inFlight: false };
        }
    }

    /** Снимает попытку входа и её debounce, возвращая Promise сохранения метаданных. */
    clearRecovery() {
        if (this.recovery) {
            clearTimeout(this.syncTimer);
            this.syncTimer = null;
        }
        this.recovery = null;
        return this.recoveryChanged(this);
    }

    /**
     * Принимает упорядоченное наблюдение DOM от вкладки данного контекста.
     * Видимый логин закрепляет текущую ревизию; его исчезновение разрешает refresh.
     * documentId/sequence отсекают старые документы и сообщения без перебазирования
     * попытки входа на более новую серверную ревизию.
     */
    async authStateChanged(tabId, state) {
        const generation = this.generation;
        if (!this.alive || !this.settings.enabled || !this.tabIds.has(tabId)
            || state.ready !== true || typeof state.loginVisible !== 'boolean'
            || state.authenticated !== !state.loginVisible
            || typeof state.documentId !== 'string' || !state.documentId
            || !Number.isInteger(state.sequence) || state.sequence < 1) return;
        const previous = this.authStates.get(tabId);
        if (previous?.documentId === state.documentId && state.sequence <= previous.sequence
            && !(previous.waitingForRevision && state.loginVisible && this.latestRevision >= 0)) return;
        if (previous?.retired.has(state.documentId)) return;
        const retired = previous?.retired || new Set();
        if (previous && previous.documentId !== state.documentId) retired.add(previous.documentId);
        const sameDialog = previous?.documentId === state.documentId && previous.loginVisible;
        const observedRevision = state.loginVisible
            ? (sameDialog && previous.observedRevision >= 0 ? previous.observedRevision : this.latestRevision)
            : (previous?.observedRevision ?? -1);
        this.authStates.set(tabId, {
            documentId: state.documentId, sequence: state.sequence, ready: state.ready,
            loginVisible: state.loginVisible, authenticated: state.authenticated,
            observedRevision, retired, waitingForRevision: state.loginVisible && this.latestRevision < 0,
        });
        let shouldSync = false;
        if (state.loginVisible) {
            if (this.latestRevision >= 0 && (!this.recovery
                || (this.recovery.tabId === tabId && !previous?.loginVisible))) {
                this.recovery = { tabId, expectedRevision: observedRevision, ready: false, inFlight: false };
                clearTimeout(this.remoteRetryTimer);
                this.remoteRetryTimer = null;
            }
        } else if (this.recovery?.tabId === tabId) {
            this.recovery.ready = true;
            shouldSync = true;
        } else if (previous?.loginVisible && observedRevision >= 0 && observedRevision === this.latestRevision
            && !this.recovery?.inFlight) {
            // Several office tabs may show the same login dialog. The tab that
            // actually completes login may take over using its own pinned revision.
            this.recovery = { tabId, expectedRevision: observedRevision, ready: true, inFlight: false };
            shouldSync = true;
        } else if (previous?.loginVisible && this.initialPending) {
            shouldSync = true;
        }
        await this.recoveryChanged(this);
        if (shouldSync && this.alive && generation === this.generation) this.scheduleSync();
    }

    /** Удаляет наблюдения закрытой/ушедшей из office вкладки и связанный recovery. */
    tabRemoved(tabId) {
        this.authStates.delete(tabId);
        if (this.recovery?.tabId === tabId) {
            this.clearRecovery().catch(error => console.warn('[CookieSync] Could not clear closed login tab:', error));
        } else {
            this.recoveryChanged(this).catch(error => console.warn('[CookieSync] Could not clear closed tab observation:', error));
        }
    }

    /** Запрашивает DOM-вердикт вкладки, при необходимости внедряя content script. */
    async readAuthentication(tabId) {
        let reply = await this.withTimeout(browser.tabs.sendMessage(tabId, { type: 'cookiesyncCheckAuthState' }));
        if (!reply || typeof reply.authenticated !== 'boolean') {
            const injected = await this.withTimeout(browser.scripting.executeScript({
                target: { tabId, frameIds: [0] }, files: ['browser-polyfill.min.js', 'authentication.js'],
            }));
            if (!injected) return undefined;
            reply = await this.withTimeout(browser.tabs.sendMessage(tabId, { type: 'cookiesyncCheckAuthState' }));
        }
        return reply;
    }

    /** Запрашивает начальные наблюдения входа, если соединение всё ещё актуально. */
    async watchAuthentication(connection, generation) {
        const store = await this.currentStore();
        if (!store || !this.isCurrent(connection, generation)) return;
        await this.isAuthenticated(store);
    }

    /**
     * Подтверждает вход через content script только во вкладках указанного store.
     * @param {Object} store Свежий снимок cookie store с tabIds.
     * @param {number|null} [requiredTabId=null] Ограничивает проверку вкладкой recovery.
     * @returns {Promise<boolean>} false, если подходящих вкладок или ответа нет.
     */
    async isAuthenticated(store, requiredTabId = null) {
        const generation = this.generation;
        const tabs = await browser.tabs.query({ url: ['*://office.reso.ru/*'] });
        const candidates = tabs.filter(tab => !tab.discarded && store.tabIds.includes(tab.id)
            && (requiredTabId === null || tab.id === requiredTabId));
        let authenticated = false;
        for (const tab of candidates) {
            const reply = await this.readAuthentication(tab.id);
            if (!this.alive || generation !== this.generation) return false;
            if (reply) await this.authStateChanged(tab.id, reply);
            if (reply?.authenticated === true) authenticated = true;
        }
        if (authenticated) return true;
        console.warn(`[CookieSync] ${this.storeId}: вход в РЕСО Офис не подтверждён`);
        return false;
    }

    /** Возвращает результат Promise либо undefined при отказе/таймауте в 3 секунды. */
    withTimeout(promise) {
        return new Promise(resolve => {
            const timer = setTimeout(() => resolve(undefined), 3000);
            promise.then(value => { clearTimeout(timer); resolve(value); },
                () => { clearTimeout(timer); resolve(undefined); });
        });
    }

    /** Перезапускает debounce в 1500 мс; initialOnly ограничивает отправку пустым аккаунтом. */
    scheduleSync(initialOnly = false) {
        if (!this.alive || !this.settings.enabled || !this.registered) return;
        clearTimeout(this.syncTimer);
        this.syncTimer = setTimeout(() => {
            this.syncTimer = null;
            this.syncCookies(initialOnly);
        }, 1500);
    }

    /**
     * После подтверждения входа читает полную пару своего store и отправляет set/refresh.
     * Ожидает applyQueue и повторно проверяет поколение после async-операций.
     * Recovery владеет inFlight до finally; конфликт не переносит попытку на новую ревизию.
     * @param {boolean} [initialOnly=false] Отправлять только при initialPending.
     */
    async syncCookies(initialOnly = false) {
        const connection = this.socket;
        const generation = this.generation;
        const current = () => this.isCurrent(connection, generation) && this.registered;
        const canSend = () => current() && (!initialOnly || this.initialPending);
        if (!canSend()) return;
        let recovery = this.recovery;
        let submittedRecovery = null;
        try {
            const store = await this.currentStore();
            if (!store || !canSend()) return;
            const authenticated = await this.isAuthenticated(store, this.recovery?.tabId ?? null);
            if (!canSend()) return;
            if (!authenticated) {
                if (this.initialPending || this.recovery) this.setPhase('online', 'Cookies не отправлены: откройте office.reso.ru и подтвердите вход в этом контексте');
                return;
            }
            recovery = this.recovery;
            if (recovery && (!recovery.ready || recovery.inFlight)) return;
            if (recovery) {
                // Claim this attempt before any asynchronous cookie preparation.
                recovery.inFlight = true;
                submittedRecovery = recovery;
            }
            await this.applyQueue;
            if (!canSend() || this.recovery !== recovery) return;
            const lists = await Promise.all(this.settings.cookieDomains.map(domain => browser.cookies.getAll({
                domain: normalizeDomain(domain), storeId: this.storeId,
            })));
            if (!canSend() || this.recovery !== recovery) return;
            const unique = new Map();
            for (const cookie of lists.flat()) unique.set(cookieKey(cookie), cookie);
            const payload = selectSyncCookiePair([...unique.values()], this.settings.cookieDomains).map(pickCookieFields);
            if (payload.length !== 2 || hasExpiredCookies(payload)) {
                if (!recovery && this.latestPayload.length === 2) await this.applyCookies(this.latestPayload, this.latestRevision);
                if (current() && (this.initialPending || recovery)) this.setPhase('online', 'Cookies не отправлены: нужна полная пара ASP.NET_SessionId и ResoOffice60');
                return;
            }
            if (recovery) {
                clearTimeout(this.syncTimer);
                this.syncTimer = null;
            }
            const response = await this.sendCommand(recovery ? 'refresh' : 'set', payload, recovery);
            if (!current()) return;
            this.initialPending = Array.isArray(response.payload) && response.payload.length === 0;
            if (response.accepted === false && this.initialPending) {
                // An account can be empty after expiry cleanup. Initialize it via
                // ordinary set; never rebase the failed refresh onto a new revision.
                this.setPhase('online', 'Серверное хранилище пусто; проверка локальных cookies');
                this.scheduleSync(true);
            } else if (response.accepted === false) {
                this.setPhase('online', recovery ? 'Другой клиент уже обновил сессию; используется серверная ревизия'
                    : `Обновление заблокировано ещё на ${response.retry_after || 0} с`);
            } else {
                this.setPhase('online', response.applied ? '' : 'Cookies сохранены на сервере, локальное применение ожидается');
            }
        } catch (error) {
            console.warn(`[CookieSync] Cookie sync failed for ${this.storeId}:`, error);
            if (current() && recovery && this.recovery === recovery) this.setPhase('error', `Обновление после входа не выполнено: ${error.message}. Проверьте версию сервера`);
            else if (current() && this.initialPending) this.setPhase('online', 'Cookies не отправлены: ошибка чтения или отправки');
        } finally {
            if (submittedRecovery) submittedRecovery.inFlight = false;
        }
    }

    /** Отсекает чужие cookies и ожидаемые удалённые изменения перед debounce. */
    cookieChanged(change) {
        const cookie = change.cookie;
        if (cookie.storeId !== this.storeId || !isCookieForSync(cookie, this.settings.cookieDomains)) return;
        if (isExpectedRemoteChange(this.expectedChanges, cookie, 2000, Date.now(), change.removed, change.cause)) return;
        this.scheduleSync();
    }

    /** Очищает вход при уходе из office и повторяет начальную отправку после загрузки. */
    tabUpdated(tabId, changeInfo, tab) {
        if (tab.url) {
            try {
                if (new URL(tab.url).hostname !== 'office.reso.ru') this.tabRemoved(tabId);
            } catch (error) { this.tabRemoved(tabId); }
        }
        if (!this.initialPending || !this.tabIds.has(tabId) || changeInfo.status !== 'complete' || !tab.url) return;
        try {
            if (new URL(tab.url).hostname === 'office.reso.ru') this.scheduleSync(true);
        } catch (error) {
            console.debug('[CookieSync] Ignoring tab without a valid URL');
        }
    }
}
