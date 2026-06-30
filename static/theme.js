/**
 * Theme toggle — flips data-theme between "dark" and "light" and persists the
 * choice in localStorage. The initial theme is set by an inline script in
 * <head> to avoid a flash of the wrong palette before this script runs.
 */
(function () {
  const btn = document.getElementById("themeToggle");
  if (!btn) return;

  btn.addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || "dark";
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("gm_theme", next);
    } catch (_) {
      /* localStorage unavailable (private mode) — theme just won't persist. */
    }
  });
})();
