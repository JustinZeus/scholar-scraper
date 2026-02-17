(() => {
  const body = document.body;
  if (!body) {
    return;
  }

  const defaultLoadingText = "Working...";

  const shouldHandleAnchor = (anchor) => {
    if (!anchor || !anchor.getAttribute) {
      return false;
    }
    const href = anchor.getAttribute("href");
    if (!href) {
      return false;
    }
    if (href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("javascript:")) {
      return false;
    }
    if (anchor.hasAttribute("download")) {
      return false;
    }
    if ((anchor.getAttribute("target") || "").toLowerCase() === "_blank") {
      return false;
    }
    return true;
  };

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const anchor = target.closest("a");
    if (!shouldHandleAnchor(anchor)) {
      return;
    }
    body.classList.add("is-page-loading");
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    if (form.dataset.noLoading === "1") {
      return;
    }

    body.classList.add("is-page-loading");
    form.classList.add("is-loading");

    const submitElements = form.querySelectorAll("button[type='submit'], input[type='submit']");
    submitElements.forEach((element) => {
      if (element.hasAttribute("disabled")) {
        return;
      }
      element.setAttribute("disabled", "disabled");
      if (element instanceof HTMLInputElement) {
        const loadingText = element.dataset.loadingText || defaultLoadingText;
        element.dataset.originalValue = element.value;
        element.value = loadingText;
        return;
      }
      if (element instanceof HTMLButtonElement) {
        const loadingText = element.dataset.loadingText || defaultLoadingText;
        element.dataset.originalText = element.textContent || "";
        element.textContent = loadingText;
      }
    });
  });

  window.addEventListener("pageshow", () => {
    body.classList.remove("is-page-loading");
  });
})();
