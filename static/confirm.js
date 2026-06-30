// Confirmation dialogs without inline handlers (so the CSP can forbid inline JS).
// Any <form data-confirm="message"> asks before submitting.
(function () {
  document.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      if (!form || !form.getAttribute) return;
      var message = form.getAttribute("data-confirm");
      if (message && !window.confirm(message)) {
        event.preventDefault();
      }
    },
    true,
  );
})();
