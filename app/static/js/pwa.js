(function () {
  "use strict";

  var installPrompt = null;
  var installButton = document.getElementById("pwa-install");
  var settings = document.getElementById("pwa-settings");
  var pushButton = document.getElementById("push-enable");
  var pushStatus = document.getElementById("push-status");
  var pushPrompt = document.getElementById("pwa-push-prompt");
  var pushPromptMessage = document.getElementById("pwa-push-message");
  var pushPromptButton = document.getElementById("pwa-push-allow");
  var pushPromptDismiss = document.getElementById("pwa-push-dismiss");

  function isInstalled() {
    return window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;
  }

  function serviceWorkerReady() {
    if (!("serviceWorker" in navigator)) {
      return Promise.reject(new Error("This browser does not support service workers."));
    }
    return navigator.serviceWorker.register("/sw.js", { scope: "/" });
  }

  function setPushMessage(message) {
    if (pushStatus) pushStatus.textContent = message;
  }

  function setPushButtonLabel(message) {
    var label = document.getElementById("push-button-label");
    if (label) label.textContent = message;
  }

  function showPushPrompt(message, canEnable) {
    if (!pushPrompt) return;
    pushPrompt.hidden = false;
    if (pushPromptMessage) pushPromptMessage.textContent = message;
    if (pushPromptButton) pushPromptButton.hidden = !canEnable;
    if (pushPromptDismiss) pushPromptDismiss.hidden = !canEnable;
  }

  function base64ToBytes(value) {
    var padding = "=".repeat((4 - value.length % 4) % 4);
    var decoded = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
    var bytes = new Uint8Array(decoded.length);
    for (var i = 0; i < decoded.length; i += 1) bytes[i] = decoded.charCodeAt(i);
    return bytes;
  }

  function updateNotificationCount() {
    var badge = document.getElementById("unread-notification-count");
    if (!badge) return;
    var count = Number.parseInt(badge.textContent, 10) || 0;
    badge.textContent = String(count + 1);
    badge.hidden = false;
  }

  function showLiveNotification(notification) {
    updateNotificationCount();
    var container = document.getElementById("live-notification");
    if (container) {
      var toast = document.createElement("div");
      toast.className = "toast show";
      toast.setAttribute("role", "status");
      var header = document.createElement("div");
      header.className = "toast-header";
      var heading = document.createElement("strong");
      heading.className = "me-auto";
      heading.textContent = notification.title;
      var close = document.createElement("button");
      close.type = "button";
      close.className = "btn-close";
      close.setAttribute("aria-label", "Close");
      close.addEventListener("click", function () { toast.remove(); });
      header.append(heading, close);
      var body = document.createElement("div");
      body.className = "toast-body";
      body.textContent = notification.body;
      var link = document.createElement("a");
      link.className = "small d-block px-3 pb-2";
      link.href = notification.url;
      link.textContent = "Open notification";
      toast.append(header, body, link);
      container.appendChild(toast);
      window.setTimeout(function () { toast.remove(); }, 12000);
    }

    var list = document.getElementById("notification-list");
    if (list) {
      var item = document.createElement("a");
      item.className = "list-group-item list-group-item-action py-3";
      item.href = notification.url;
      var title = document.createElement("strong");
      title.textContent = notification.title;
      var unread = document.createElement("span");
      unread.className = "badge text-bg-primary ms-2";
      unread.textContent = "Unread";
      var summary = document.createElement("div");
      summary.className = "text-muted text-truncate";
      summary.textContent = notification.body;
      item.append(title, unread, summary);
      list.prepend(item);
    }
  }

  function startLiveUpdates() {
    if (!settings || !settings.dataset.streamUrl || !("EventSource" in window)) return;
    var url = new URL(settings.dataset.streamUrl, window.location.origin);
    url.searchParams.set("after", settings.dataset.notificationCursor || "0");
    var stream = new EventSource(url);
    stream.addEventListener("notification", function (event) {
      try {
        var notification = JSON.parse(event.data);
        showLiveNotification(notification);
      } catch (error) {
        console.error("Could not read the live notification event.", error);
      }
    });
  }

  async function sendSubscription(endpoint, method, subscription) {
    var response = await fetch(endpoint, {
      method: method,
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": settings.dataset.csrfToken
      },
      body: JSON.stringify(subscription)
    });
    var result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not update notification settings.");
    return result;
  }

  async function enablePush(config) {
    if (!("Notification" in window) || !("PushManager" in window)) {
      throw new Error("Push notifications are not supported by this browser.");
    }
    var permission = Notification.permission;
    if (permission === "default") permission = await Notification.requestPermission();
    if (permission !== "granted") {
      throw new Error("Allow notifications in your browser settings to receive phone alerts.");
    }
    var registration = await serviceWorkerReady();
    var subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: base64ToBytes(config.publicKey)
      });
    }
    await sendSubscription(settings.dataset.pushSubscribeUrl, "POST", subscription.toJSON());
    setPushButtonLabel("Turn off alerts");
    pushButton.setAttribute("aria-label", "Turn off phone notifications");
    pushButton.title = "Turn off phone notifications";
    pushButton.dataset.enabled = "true";
    setPushMessage("Phone notifications are enabled.");
    if (pushPrompt) pushPrompt.hidden = true;
  }

  async function disablePush() {
    var registration = await serviceWorkerReady();
    var subscription = await registration.pushManager.getSubscription();
    if (subscription) {
      await sendSubscription(settings.dataset.pushSubscribeUrl, "DELETE", subscription.toJSON());
      await subscription.unsubscribe();
    }
    setPushButtonLabel("Phone alerts");
    pushButton.setAttribute("aria-label", "Enable phone notifications");
    pushButton.title = "Enable phone notifications";
    pushButton.dataset.enabled = "false";
    setPushMessage("Phone notifications are turned off.");
  }

  async function setupPush() {
    if (!settings || !pushButton) return;
    if (!("Notification" in window) || !("PushManager" in window)) {
      pushButton.hidden = true;
      if (isInstalled()) {
        showPushPrompt(
          "This browser does not support phone push notifications. Update your browser or install the app from a supported browser.",
          false
        );
      }
      return;
    }
    if (!window.isSecureContext) {
      pushButton.disabled = true;
      setPushMessage("Phone notifications require a secure HTTPS connection.");
      if (isInstalled()) {
        showPushPrompt("Phone notifications need the app to be opened from its secure HTTPS address.", false);
      }
      return;
    }
    try {
      var response = await fetch(settings.dataset.pushConfigUrl, { credentials: "same-origin" });
      var config = await response.json();
      if (!response.ok) throw new Error(config.error || "Could not load push settings.");
      if (!config.enabled) {
        pushButton.disabled = true;
        pushButton.title = config.error || "Ask the administrator to configure web-push keys.";
        setPushMessage(config.error || "Phone notifications are not configured on this server yet.");
        return;
      }
      var statusResponse = await fetch(settings.dataset.pushStatusUrl, { credentials: "same-origin" });
      var status = await statusResponse.json();
      if (!statusResponse.ok) throw new Error(status.error || "Could not load notification status.");
      pushButton.title = status.subscribed ? "Turn off phone notifications" : "Enable phone notifications";
      if (Notification.permission === "granted") {
        await enablePush(config);
      } else if (status.subscribed) {
        setPushButtonLabel("Enable alerts");
      }
      if (isInstalled() && Notification.permission === "default") {
        showPushPrompt("Allow notifications to receive new notices on this phone.", true);
      } else if (isInstalled() && Notification.permission === "denied") {
        showPushPrompt(
          "Notifications are blocked for this app. Allow them in your phone's app or browser notification settings.",
          false
        );
      }

      async function handlePushButtonClick() {
        pushButton.disabled = true;
        try {
          if (pushButton.dataset.enabled === "true") await disablePush();
          else await enablePush(config);
        } catch (error) {
          setPushMessage(error.message);
          if (isInstalled()) showPushPrompt(error.message, Notification.permission !== "denied");
        } finally {
          pushButton.disabled = false;
        }
      }

      pushButton.addEventListener("click", handlePushButtonClick);
      if (pushPromptButton) {
        pushPromptButton.addEventListener("click", async function () {
          pushPromptButton.disabled = true;
          try {
            await enablePush(config);
          } catch (error) {
            setPushMessage(error.message);
            showPushPrompt(error.message, Notification.permission !== "denied");
          } finally {
            pushPromptButton.disabled = false;
          }
        });
      }
    } catch (error) {
      pushButton.disabled = true;
      setPushMessage(error.message);
      if (isInstalled()) showPushPrompt(error.message, false);
    }
  }

  if (pushPromptDismiss) {
    pushPromptDismiss.addEventListener("click", function () {
      pushPrompt.hidden = true;
    });
  }

  if ("serviceWorker" in navigator) {
    serviceWorkerReady().catch(function (error) {
      console.error("Could not register the EduManage service worker.", error);
    });
  }

  if (installButton) {
    if (isInstalled()) {
      installButton.hidden = true;
    } else {
      installButton.hidden = false;
      installButton.addEventListener("click", async function () {
        if (!installPrompt) {
          window.alert("To install EduManage, use your browser menu and choose Install app or Add to Home Screen.");
          return;
        }
        installPrompt.prompt();
        await installPrompt.userChoice;
        installPrompt = null;
        installButton.hidden = true;
      });
    }
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    installPrompt = event;
    if (installButton && !isInstalled()) installButton.hidden = false;
  });
  window.addEventListener("appinstalled", function () {
    installPrompt = null;
    if (installButton) installButton.hidden = true;
  });

  startLiveUpdates();
  setupPush();
}());
