// Wird im <head> geladen, damit beim Seitenaufbau kein Farbblitz entsteht.
(function () {
  try {
    var t = localStorage.getItem("mietly-theme");
    if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
  } catch (e) { /* Speicher nicht verfügbar */ }
})();
