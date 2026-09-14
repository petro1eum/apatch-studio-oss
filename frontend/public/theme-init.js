(function () {
  try {
    var theme = localStorage.getItem("apatch-studio-theme");
    if (theme !== "light" && theme !== "dark") theme = "system";
    document.documentElement.setAttribute("data-theme", theme);
  } catch (_error) {
    document.documentElement.setAttribute("data-theme", "system");
  }
})();
