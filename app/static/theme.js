(() => {
  const STORAGE_KEY = "scholarr_theme";
  const LEGACY_STORAGE_KEY = "scholar_tracker_theme";
  const root = document.documentElement;
  const themeControl = document.querySelector("[data-theme-control]");

  if (!root) {
    return;
  }

  const defaultTheme = root.dataset.defaultTheme || "terracotta";
  const supportedThemes = themeControl
    ? Array.from(themeControl.options).map((option) => option.value)
    : [];

  const isSupported = (theme) =>
    supportedThemes.length === 0 || supportedThemes.includes(theme);

  const applyTheme = (theme) => {
    if (!isSupported(theme)) {
      return;
    }
    root.dataset.theme = theme;
  };

  let activeTheme = defaultTheme;
  try {
    const savedTheme = window.localStorage.getItem(STORAGE_KEY);
    const legacyTheme = window.localStorage.getItem(LEGACY_STORAGE_KEY);
    if (savedTheme && isSupported(savedTheme)) {
      activeTheme = savedTheme;
    } else if (legacyTheme && isSupported(legacyTheme)) {
      activeTheme = legacyTheme;
      window.localStorage.setItem(STORAGE_KEY, legacyTheme);
    }
  } catch {
    activeTheme = defaultTheme;
  }

  applyTheme(activeTheme);

  if (!themeControl) {
    return;
  }

  themeControl.value = activeTheme;
  themeControl.addEventListener("change", (event) => {
    const selectedTheme = event.target.value;
    applyTheme(selectedTheme);
    try {
      window.localStorage.setItem(STORAGE_KEY, selectedTheme);
    } catch {
      // Ignore storage errors in locked-down browsers.
    }
  });
})();
