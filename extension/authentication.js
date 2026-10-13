// Content script для office.reso.ru: сообщает фоновому скрипту, аутентифицирован
// ли пользователь. Признак входа — отсутствие видимого окна логина РЕСО Офис:
//
//   <div id="clbkAuth_ASPxPopupControl1_loginTitle2" class="login-title">
//       Добро пожаловать в РЕСО Офис</div>

// Может подключаться повторно из background к вкладке, открытой до установки.
(() => {
    if (location.hostname !== 'office.reso.ru' || globalThis.cookieSyncAuthInstalled) {
        return;
    }

    const LOGIN_TITLE_SELECTOR = '#clbkAuth_ASPxPopupControl1_loginTitle2';

    function isLoginPopupVisible() {
        const element = document.querySelector(LOGIN_TITLE_SELECTOR);
        if (!element) {
            return false;
        }

        // ASPx оставляет скрытое окно входа в DOM после авторизации.
        return element.offsetParent !== null || element.getClientRects().length > 0;
    }

    browser.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (request && request.type === 'cookiesyncCheckAuth') {
            sendResponse({
                authenticated: document.readyState !== 'loading' && !isLoginPopupVisible(),
            });
        }
    });
    globalThis.cookieSyncAuthInstalled = true;
})();
