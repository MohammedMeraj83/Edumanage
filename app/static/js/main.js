// Confirmation modal: any button with data-confirm opens the shared modal and,
// on "Yes", submits the form given by data-form (a form id) or its own parent form.

// Confirmation modal
document.addEventListener("DOMContentLoaded", function () {
  var modalEl = document.getElementById("confirmModal");
  if (!modalEl || !window.bootstrap) return;

  var modal = new bootstrap.Modal(modalEl);
  var pendingForm = null;
  var pendingButton = null;

  document.querySelectorAll("[data-confirm]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();

      pendingForm = btn.closest("form");
      pendingButton = btn;

      modalEl.querySelector(".modal-title").textContent =
        btn.dataset.title || "Are you sure?";

      modalEl.querySelector(".modal-body").textContent =
        btn.dataset.confirm;

      var ok = modalEl.querySelector("[data-ok]");
      ok.textContent = btn.dataset.okLabel || "Yes, continue";
      ok.className = "btn " + (btn.dataset.okClass || "btn-danger");

      modal.show();
    });
  });

  modalEl.querySelector("[data-ok]").addEventListener("click", function () {
    if (pendingForm && pendingButton) {
      pendingForm.requestSubmit(pendingButton);
    }

    pendingForm = null;
    pendingButton = null;
    modal.hide();
  });
});
