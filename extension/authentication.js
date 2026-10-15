/**
 * @file Идемпотентный content script наблюдения входа на office.reso.ru.
 * DOM-эвристика: после loading отсутствие видимого заголовка окна логина
 * #clbkAuth_ASPxPopupControl1_loginTitle2 считается подтверждением входа.
 * documentId и sequence позволяют background отсеивать устаревшие наблюдения.
 */

// Может подключаться повторно из background к вкладке, открытой до установки.
(() => {
    if (location.hostname !== 'office.reso.ru' || globalThis.cookieSyncAuthInstalled === 2) {
        return;
    }

    const LOGIN_TITLE_SELECTOR = '#clbkAuth_ASPxPopupControl1_loginTitle2';
    // HTTP office pages don't expose randomUUID(), even though getRandomValues
    // is available. This is a local document nonce, not a protocol request UUID.
    const documentId = typeof crypto.randomUUID === 'function' ? crypto.randomUUID()
        : Array.from(crypto.getRandomValues(new Uint32Array(4)), value => value.toString(16)).join('-');
    let sequence = 0;
    let previous = '';

    /** Проверяет layout окна логина, которое ASPx может оставлять скрытым в DOM. */
    function isLoginPopupVisible() {
        const element = document.querySelector(LOGIN_TITLE_SELECTOR);
        if (!element) {
            return false;
        }

        // ASPx оставляет скрытое окно входа в DOM после авторизации.
        return element.offsetParent !== null || element.getClientRects().length > 0;
    }

    /**
     * Возвращает текущий DOM-вердикт и отправляет событие только при изменении состояния.
     * sequence возрастает внутри одного документа; loading никогда не подтверждает вход.
     */
    function reportState() {
        const ready = document.readyState !== 'loading';
        const loginVisible = isLoginPopupVisible();
        const authenticated = ready && !loginVisible;
        const signature = `${ready}:${loginVisible}`;
        if (signature !== previous) {
            previous = signature;
            sequence += 1;
            browser.runtime.sendMessage({
                type: 'cookiesyncAuthState', documentId, sequence, ready, loginVisible, authenticated,
            }).catch(() => {}); // Background may be updating or not available yet.
        }
        return { documentId, sequence, ready, loginVisible, authenticated };
    }

    browser.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (['cookiesyncCheckAuth', 'cookiesyncCheckAuthState'].includes(request?.type)) {
            sendResponse(reportState());
        }
    });
    const observer = new MutationObserver(reportState);
    observer.observe(document.documentElement, {
        subtree: true, childList: true, attributes: true, attributeFilter: ['style', 'class', 'hidden'],
    });
    document.addEventListener('readystatechange', reportState);
    document.addEventListener('transitionend', reportState);
    document.addEventListener('animationend', reportState);
    window.addEventListener('pageshow', reportState);
    window.addEventListener('resize', reportState);
    globalThis.cookieSyncAuthInstalled = 2;
    reportState();
})();
