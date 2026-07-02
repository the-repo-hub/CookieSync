const accountInput = document.getElementById('accountInput');
const serverUrlInput = document.getElementById('serverUrlInput');
const enableToggle = document.getElementById('enableToggle');
const toggleContainer = document.getElementById('toggleContainer');
const accountError = document.getElementById('accountError');
const serverError = document.getElementById('serverError');

function validateInputs() {
    let isValid = true;
    accountError.textContent = '';
    serverError.textContent = '';
    
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

// Load settings from storage
async function loadSettings() {
    const settings = await chrome.storage.local.get(['account', 'serverUrl', 'enabled']);
    accountInput.value = settings.account || '';
    serverUrlInput.value = settings.serverUrl || 'wss://localhost:52314';
    enableToggle.checked = settings.enabled === true;
    updateToggleState();
}

// Save settings and sync with background
async function saveSettings() {
    if (!validateInputs()) {
        return;
    }
    
    const settings = {
        account: accountInput.value,
        serverUrl: serverUrlInput.value,
        enabled: enableToggle.checked
    };
    
    await chrome.storage.local.set(settings);
    
    // Notify background script
    chrome.runtime.sendMessage({
        type: 'settingsChanged',
        settings: settings
    }).catch(() => {});
}

// Event listeners
accountInput.addEventListener('input', updateToggleState);
serverUrlInput.addEventListener('input', updateToggleState);

accountInput.addEventListener('blur', saveSettings);
serverUrlInput.addEventListener('blur', saveSettings);

enableToggle.addEventListener('change', function(e) {
    if (!validateInputs()) {
        e.preventDefault();
        this.checked = false;
        return;
    }
    saveSettings();
});

// Prevent toggle when invalid
toggleContainer.addEventListener('click', function(e) {
    if (toggleContainer.classList.contains('disabled')) {
        e.preventDefault();
        e.stopPropagation();
        return false;
    }
});

// Load settings on open
loadSettings();
