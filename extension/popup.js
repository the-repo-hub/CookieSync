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

const SETTINGS_FIELDS = [accountInput, serverUrlInput, cookieDomainInput];

function setFieldsDisabled(disabled) {
    SETTINGS_FIELDS.forEach(field => {
        field.disabled = disabled;
    });
}

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

function updateToggleState() {
    const isValid = validateInputs();

    enableToggle.disabled = !isValid;

    if (isValid) {
        toggleContainer.classList.remove('disabled');
    } else {
        toggleContainer.classList.add('disabled');
        enableToggle.checked = false;
    }
}

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
        enableToggle.checked = settings.enabled;
        updateToggleState();
        setFieldsDisabled(enableToggle.checked);
        updateStatusDisplay(status.connected, settings.enabled, status.phase, status.detail, status.error);
    } catch (error) {
        showError(error);
    }
}

function showError(error) {
    syncStatus.className = 'sync-status error';
    syncStatus.textContent = `Ошибка: ${error.message || error}`;
}

function saveSettings() {
    if (!validateInputs()) {
        return;
    }

    const domains = cookieDomainInput.value
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);

    const settings = {
        account: accountInput.value.trim(),
        serverUrl: serverUrlInput.value.trim(),
        cookieDomains: domains.length ? domains : ['.reso.ru'],
        enabled: enableToggle.checked
    };

    const request = {
        type: 'saveSettings', tabId: boundTabId, contextId: boundContext.contextId, settings,
    };
    saveQueue = saveQueue.then(async () => {
        const status = await browser.runtime.sendMessage(request);
        updateStatusDisplay(status.connected, status.settings.enabled, status.phase, status.detail, status.error);
    }).catch(showError);
    return saveQueue;
}

// Event listeners
accountInput.addEventListener('input', updateToggleState);
serverUrlInput.addEventListener('input', updateToggleState);
cookieDomainInput.addEventListener('input', updateToggleState);

accountInput.addEventListener('blur', saveSettings);
serverUrlInput.addEventListener('blur', saveSettings);
cookieDomainInput.addEventListener('blur', saveSettings);

enableToggle.addEventListener('change', function () {
    if (!validateInputs()) {
        this.checked = false;
        return;
    }
    saveSettings();
    setFieldsDisabled(this.checked);
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
        browser.runtime.sendMessage({
            type: 'getContext', tabId: boundTabId, contextId: boundContext.contextId,
        }).then(status => {
            updateStatusDisplay(status.connected, status.settings.enabled, status.phase, status.detail, status.error);
        }).catch(showError);
    }
});

loadSettings();
