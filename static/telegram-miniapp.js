// Keep the Telegram bridge optional: the same player also runs in a normal browser.
(() => {
  const app = window.Telegram?.WebApp;
  const launchParams = `${window.location.search}${window.location.hash}`;
  if (!app || !(app.initData || (app.platform && app.platform !== "unknown") || /tgWebApp(?:Version|Platform|Data)=/.test(launchParams))) return;

  const root = document.documentElement;
  root.classList.add("telegram-miniapp");

  function updateViewport() {
    const content = app.contentSafeAreaInset || {};
    const device = app.safeAreaInset || {};
    for (const edge of ["top", "right", "bottom", "left"]) {
      const contentValue = Number(content[edge]);
      const deviceValue = Number(device[edge]);
      root.style.setProperty(`--miniapp-content-${edge}`, `${Number.isFinite(contentValue) ? Math.max(0, contentValue) : 0}px`);
      root.style.setProperty(`--miniapp-device-${edge}`, `${Number.isFinite(deviceValue) ? Math.max(0, deviceValue) : 0}px`);
    }
    root.classList.toggle("telegram-fullscreen", Boolean(app.isFullscreen));
  }

  updateViewport();
  app.onEvent?.("contentSafeAreaChanged", updateViewport);
  app.onEvent?.("safeAreaChanged", updateViewport);
  app.onEvent?.("fullscreenChanged", updateViewport);
  app.onEvent?.("viewportChanged", updateViewport);
  app.expand?.();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => app.ready?.(), { once: true });
  } else {
    app.ready?.();
  }
})();
