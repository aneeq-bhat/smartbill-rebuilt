// Keep client-side behaviour progressive: core workflows work without JavaScript.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-confirm]").forEach((el) => {
    el.addEventListener("click", (event) => {
      if (!window.confirm(el.dataset.confirm || "Continue?")) event.preventDefault();
    });
  });
});
