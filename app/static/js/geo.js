// Forms with class "geo-form" collect the phone's location right before they are sent.
// The server then checks that the person is really inside the tuition area.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("form.geo-form").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (form.dataset.geoDone === "1") return;
      e.preventDefault();
      var btn = form.querySelector("button:not([type=button])");
      var status = form.querySelector(".geo-status");
      function say(msg) { if (status) { status.textContent = msg; status.classList.remove("d-none"); } }
      function restore() { if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label; } }
      if (btn) { btn.dataset.label = btn.textContent; btn.disabled = true; btn.textContent = "Getting your location…"; }
      if (!window.isSecureContext) { say("Location needs a secure (https) connection."); restore(); return; }
      if (!navigator.geolocation) { say("This browser cannot share location."); restore(); return; }
      navigator.geolocation.getCurrentPosition(function (pos) {
        form.querySelector("[name=lat]").value = pos.coords.latitude;
        form.querySelector("[name=lng]").value = pos.coords.longitude;
        form.querySelector("[name=accuracy]").value = pos.coords.accuracy;
        form.dataset.geoDone = "1";
        form.submit();
      }, function (err) {
        say(err.code === 1 ? "Location is blocked. Allow location for this site in your browser settings, then try again."
                           : "Could not get your location. Turn on GPS and try again.");
        restore();
      }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
    });
  });
});
