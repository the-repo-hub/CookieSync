/**
 * @file UI настроек контекста активной вкладки через runtime-сообщения background.
 * Переключатель отражает подтверждённое состояние; сохранения выполняются по очереди,
 * а версии действий и запросов защищают UI от запоздавших ответов статуса.
 */
const accountInput = document.getElementById('accountInput');
const serverUrlInput = document.getElementById('serverUrlInput');
const cookieDomainInput = document.getElementById('cookieDomainInput');
const enableToggle = document.getElementById('enableToggle');
const toggleContainer = document.getElementById('toggleContainer');
const accountError = document.getElementById('accountError');
const serverError = document.getElementById('serverError');
const domainError = document.getElementById('domainError');
const syncStatus = document.getElementById('syncStatus');
let boundContext = null;
let boundTabId = null;
let saveQueue = Promise.resolve();
let confirmedEnabled = false;
let toggleSaving = false;
let actionVersion = 0;
let statusRequest = 0;
let statusDirty = false;

const SETTINGS_FIELDS = [accountInput, serverUrlInput, cookieDomainInput];

/** Разрешает или запрещает редактирование полей соединения и аккаунта. */
function setFieldsDisabled(disabled) {
    SETTINGS_FIELDS.forEach(field => {
        field.disabled = disabled;
    });
}

/** Показывает ошибки полей и возвращает возможность сохранить текущую форму. */
function validateInputs() {
    let isValid = boundContext !== null;
    accountError.textContent = '';
    serverError.textContent = '';
    domainError.textContent = '';

    if (!accountInput.value.trim()) {
        accountInput.classList.add('error');
        accountError.textContent = 'Обязательное поле';
        isValid = false;
    } else {
        accountInput.classList.remove('error');
    }

    if (!serverUrlInput.value.trim()) {
        serverUrlInput.classList.add('error');
        serverError.textContent = 'Обязательное поле';
        isValid = false;
    } else {
        serverUrlInput.classList.remove('error');
        try {
            validateSyncSettings({ serverUrl: serverUrlInput.value });
        } catch (error) {
            serverUrlInput.classList.add('error');
            serverError.textContent = error.message;
            isValid = false;
        }
    }

    if (!cookieDomainInput.value.trim()) {
        cookieDomainInput.classList.add('error');
        domainError.textContent = 'Обязательное поле';
        isValid = false;
    } else {
        cookieDomainInput.classList.remove('error');
        const domains = cookieDomainInput.value
            .split(',')
            .map(s => s.trim())
            .filter(Boolean);
        if (!domains.length || domains.some(d => !/^\.?[a-zа-я0-9.-]+$/i.test(d))) {
            cookieDomainInput.classList.add('error');
            domainError.textContent = 'Формат: домен, через запятую (напр. .reso.ru)';
            isValid = false;
        }
    }

    return isValid;
}

/** Разрешает включение только валидной формы, а выключение — любого включённого контекста. */
function updateToggleState() {
    const isValid = validateInputs();
    const canToggle = boundContext !== null && (confirmedEnabled || isValid);

    enableToggle.disabled = toggleSaving || !canToggle;

    if (canToggle && !toggleSaving) {
        toggleContainer.classList.remove('disabled');
    } else {
        toggleContainer.classList.add('disabled');
    }
}

/** Приводит checkbox и доступность полей к последнему подтверждённому состоянию. */
function updateControls() {
    enableToggle.checked = confirmedEnabled;
    setFieldsDisabled(confirmedEnabled || toggleSaving);
    updateToggleState();
}

/** Принимает ответ background как подтверждение enabled и обновляет отображение. */
function confirmStatus(status) {
    confirmedEnabled = status.settings.enabled === true;
    updateControls();
    updateStatusDisplay(status.connected, confirmedEnabled, status.phase, status.detail, status.error);
}

/** Запрашивает статус привязанного контекста, игнорируя устаревшие ответы и ошибки. */
function refreshStatus() {
    if (!boundContext || toggleSaving) return Promise.resolve();
    const version = actionVersion;
    const requestId = ++statusRequest;
    const isCurrent = () => version === actionVersion && requestId === statusRequest && !toggleSaving;
    return browser.runtime.sendMessage({
        type: 'getContext', tabId: boundTabId, contextId: boundContext.contextId,
    }).then(status => {
        if (isCurrent()) confirmStatus(status);
    }).catch(error => {
        if (isCurrent()) showError(error);
    });
}

/** Возвращает пользовательское название фазы соединения. */
function phaseLabel(phase) {
    switch (phase) {
        case 'connecting':
            return 'Подключение';
        case 'connected':
            return 'Подключено';
        case 'registering':
            return 'Регистрация';
        case 'online':
            return 'Онлайн';
        case 'disconnected':
            return 'Переподключение';
        case 'error':
            return 'Ошибка';
        default:
            return 'Откл.';
    }
}

/**
 * Отображает фазу/ошибку; для выключенного контекста очищает строку статуса.
 * Параметр connected сохранён в интерфейсе, оформление определяется phase.
 */
function updateStatusDisplay(connected, enabled, phase, detail, error) {
    syncStatus.classList.remove('connected', 'disconnected', 'error', 'disabled', 'active');

    if (!enabled) {
        syncStatus.textContent = '';
        return;
    }

    const label = phaseLabel(phase);
    const text = detail ? `${label}: ${detail}` : label;
    syncStatus.textContent = error && phase !== 'online' ? `Ошибка: ${error}` : text;

    if (phase === 'online') {
        syncStatus.classList.add('connected');
    } else if (phase === 'error') {
        syncStatus.classList.add('error');
    } else if (phase === 'connecting' || phase === 'registering' || phase === 'connected' || phase === 'disconnected') {
        syncStatus.classList.add('active');
    } else {
        syncStatus.classList.add('disconnected');
    }
}

/** Привязывает popup к текущей активной вкладке и загружает её настройки из background. */
async function loadSettings() {
    enableToggle.disabled = true;
    setFieldsDisabled(true);
    try {
        const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
        if (!Number.isInteger(tab?.id)) throw new Error('Нет активной вкладки для выбора контекста');
        boundTabId = tab.id;
        const status = await browser.runtime.sendMessage({ type: 'getContext', tabId: boundTabId });
        boundContext = { storeId: status.storeId, contextId: status.contextId };
        const settings = status.settings;
        accountInput.value = settings.account;
        serverUrlInput.value = settings.serverUrl;
        cookieDomainInput.value = settings.cookieDomains.join(', ');
        confirmStatus(status);
    } catch (error) {
        showError(error);
    }
}

/** Выводит сообщение ошибки, сохраняя подтверждённое состояние переключателя. */
function showError(error) {
    syncStatus.className = 'sync-status error';
    syncStatus.textContent = `Ошибка: ${error.message || error}`;
}

/**
 * Ставит сохранение формы или переключение в очередь сообщений background.
 * Выключение отправляет disableContext без новых настроек и без валидации полей.
 * При отказе или потере ответа запрашивает фактическое состояние контекста.
 * @param {boolean} [enabled=confirmedEnabled] Желаемое состояние синхронизации.
 * @param {boolean} [isToggle=false] Признак действия переключателя, блокирующего UI.
 * @returns {Promise|undefined} Очередь сохранения либо undefined при невалидной форме.
 */
function saveSettings(enabled = confirmedEnabled, isToggle = false) {
    if (toggleSaving && !isToggle) return saveQueue;
    const disabling = isToggle && !enabled;
    if (!boundContext || (!disabling && !validateInputs())) {
        updateControls();
        return;
    }

    const request = {
        type: disabling ? 'disableContext' : 'saveSettings',
        tabId: boundTabId, contextId: boundContext.contextId,
    };
    if (!disabling) {
        const domains = cookieDomainInput.value.split(',').map(value => value.trim()).filter(Boolean);
        request.settings = {
            account: accountInput.value.trim(), serverUrl: serverUrlInput.value.trim(),
            cookieDomains: domains.length ? domains : ['.reso.ru'], enabled,
        };
    }
    actionVersion += 1;
    if (isToggle) {
        toggleSaving = true;
        statusDirty = false;
        updateControls();
    }
    saveQueue = saveQueue.then(async () => {
        let failed = false;
        try {
            confirmStatus(await browser.runtime.sendMessage(request));
        } catch (error) {
            failed = true;
            // A rejected save (or lost response) doesn't prove the background
            // stopped. Query its actual state, otherwise keep the last confirmed one.
            try {
                confirmStatus(await browser.runtime.sendMessage({
                    type: 'getContext', tabId: boundTabId, contextId: boundContext.contextId,
                }));
            } catch (statusError) {
                console.warn('[CookieSync] Could not confirm settings after save failure:', statusError);
            }
            showError(error);
        } finally {
            const refresh = isToggle && statusDirty && !failed;
            if (isToggle) {
                toggleSaving = false;
                statusDirty = false;
            }
            updateControls();
            if (refresh) await refreshStatus();
        }
    }).catch(showError);
    return saveQueue;
}

// Event listeners
accountInput.addEventListener('input', updateToggleState);
serverUrlInput.addEventListener('input', updateToggleState);
cookieDomainInput.addEventListener('input', updateToggleState);

accountInput.addEventListener('blur', () => saveSettings());
serverUrlInput.addEventListener('blur', () => saveSettings());
cookieDomainInput.addEventListener('blur', () => saveSettings());

enableToggle.addEventListener('change', function () {
    const requestedEnabled = this.checked;
    this.checked = confirmedEnabled;
    if (requestedEnabled && !validateInputs()) {
        updateControls();
        return;
    }
    return saveSettings(requestedEnabled, true);
});

toggleContainer.addEventListener('click', function (e) {
    if (toggleContainer.classList.contains('disabled')) {
        e.preventDefault();
        e.stopPropagation();
        return false;
    }
});

// Listen for status updates from background
browser.runtime.onMessage.addListener((message) => {
    if (message.type === 'statusUpdate' && boundContext && message.contextId === boundContext.contextId) {
        if (toggleSaving) {
            statusDirty = true;
            return;
        }
        refreshStatus();
    }
});

loadSettings();
