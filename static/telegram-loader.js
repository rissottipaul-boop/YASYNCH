// Load Telegram's bridge only for a Mini App launch. Browser visitors keep the
// regular layout and avoid a third-party request on every page load.
(() => {
  const params = `${location.search}${location.hash}`;
  const app = window.Telegram?.WebApp;
  if (!/tgWebApp(?:Version|Platform|Data)=/.test(params) &&
      !(app?.initData || (app?.platform && app.platform !== "unknown"))) return;

  document.documentElement.classList.add("telegram-miniapp");
  const bridge = document.createElement("script");
  bridge.src = "https://telegram.org/js/telegram-web-app.js?64";
  bridge.onload = () => {
    const init = document.createElement("script");
    init.src = "/assets/telegram-miniapp.js?v=tg-mobile-1";
    document.head.append(init);
  };
  document.head.append(bridge);
})();
