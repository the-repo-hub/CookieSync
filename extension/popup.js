const api = (typeof browser !== 'undefined' && browser.storage) ? browser : chrome;

const accountInput = document.getElementById('accountInput');
const serverUrlInput = document.getElementById('serverUrlInput');
const cookieDomainInput = document.getElementById('cookieDomainInput');
const probeUrlInput = document.getElementById('probeUrlInput');
const enableToggle = document.getElementById('enableToggle');
const toggleContainer = document.getElementById('toggleContainer');
const accountError = document.getElementById('accountError');
const serverError = document.getElementById('serverError');
const probeError = document.getElementById('probeError');
const syncStatus = document.getElementById('syncStatus');

const SETTINGS_FIELDS = [accountInput, serverUrlInput, cookieDomainInput, probeUrlInput];

function setFieldsDisabled(disabled) {
    SETTINGS_FIELDS.forEach(field => {
        field.disabled = disabled;
    });
}

function isHttpUrl(value) {
    return /^https?:\/\//i.test(value);
}

function validateInputs() {
    let isValid = true;
    accountError.textContent = '';
    serverError.textContent = '';
    probeError.textContent = '';

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
    }

    if (!probeUrlInput.value.trim()) {
        probeUrlInput.classList.add('error');
        probeError.textContent = 'Обязательное поле';
        isValid = false;
    } else if (!isHttpUrl(probeUrlInput.value.trim())) {
        probeUrlInput.classList.add('error');
        probeError.textContent = 'Только http:// или https://';
        isValid = false;
    } else {
        probeUrlInput.classList.remove('error');
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
    const settings = await api.storage.local.get(['account', 'serverUrl', 'enabled', 'cookieDomains', 'cookieDomain', 'probeUrl']);
    accountInput.value = settings.account || '';
    serverUrlInput.value = settings.serverUrl || 'wss://localhost:52314';
    const rawDomains = settings.cookieDomains !== undefined ? settings.cookieDomains : settings.cookieDomain;
    cookieDomainInput.value = Array.isArray(rawDomains) ? rawDomains.join(', ') : (rawDomains || '.reso.ru');
    probeUrlInput.value = settings.probeUrl || 'https://reso.ru/';
    enableToggle.checked = settings.enabled === true;
    updateToggleState();
    setFieldsDisabled(enableToggle.checked);

    try {
        const status = await api.runtime.sendMessage({ type: 'getStatus' });
        updateStatusDisplay(status.connected, status.enabled, status.phase, status.detail, status.error);
    } catch (e) {
        updateStatusDisplay(false, false, 'error', 'Нет ответа от фонового скрипта');
    }
}

async function saveSettings() {
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
        probeUrl: probeUrlInput.value.trim(),
        enabled: enableToggle.checked
    };

    await api.storage.local.set(settings);

    api.runtime.sendMessage({
        type: 'settingsChanged',
        settings: settings
    }).catch(() => {});
}

// Event listeners
accountInput.addEventListener('input', updateToggleState);
serverUrlInput.addEventListener('input', updateToggleState);
probeUrlInput.addEventListener('input', updateToggleState);

accountInput.addEventListener('blur', saveSettings);
serverUrlInput.addEventListener('blur', saveSettings);
cookieDomainInput.addEventListener('blur', saveSettings);
probeUrlInput.addEventListener('blur', saveSettings);

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
api.runtime.onMessage.addListener((message) => {
    if (message.type === 'statusUpdate') {
        api.runtime.sendMessage({ type: 'getStatus' }).then((status) => {
            updateStatusDisplay(status.connected, status.enabled, status.phase, status.detail, status.error);
        }).catch(() => {});
    }
});

loadSettings();
