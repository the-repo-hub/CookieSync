// Content script для office.reso.ru: сообщает фоновому скрипту, аутентифицирован
// ли пользователь. Признак входа — отсутствие видимого окна логина РЕСО Офис:
//
//   <div id="clbkAuth_ASPxPopupControl1_loginTitle2" class="login-title">
//       Добро пожаловать в РЕСО Офис</div>

const LOGIN_TITLE_SELECTOR = '#clbkAuth_ASPxPopupControl1_loginTitle2';

function isLoginPopupVisible() {
    const element = document.querySelector(LOGIN_TITLE_SELECTOR);
    if (!element) {
        return false;
    }

    // Элемент в DOM, но может быть скрыт (display:none / вне рендера) —
    // тогда считаем, что попап не показан, т.е. пользователь вошёл.
    return element.offsetParent !== null || element.getClientRects().length > 0;
}

browser.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request && request.type === 'cookiesyncCheckAuth') {
        sendResponse({ authenticated: !isLoginPopupVisible() });
        return;
    }
});