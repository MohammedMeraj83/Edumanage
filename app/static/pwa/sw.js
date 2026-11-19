self.addEventListener("install", function (event) {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", function (event) {
  var payload = {};
  if (event.data) {
    try {
      payload = event.data.json();
    } catch (error) {
      payload = { title: "EduManage", body: event.data.text() };
    }
  }

  var title = payload.title || "EduManage notification";
  var options = {
    body: payload.body || "You have a new update.",
    icon: "/static/pwa/icon-192.png",
    badge: "/static/pwa/icon-192.png",
    silent: false,
    vibrate: [200, 100, 200],
    tag: payload.tag,
    data: { url: payload.url || "/notifications/" }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = new URL(event.notification.data.url || "/", self.location.origin);
  if (target.origin !== self.location.origin) return;

  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (windows) {
    for (var i = 0; i < windows.length; i += 1) {
      if ("focus" in windows[i]) {
        return windows[i].navigate(target.href).then(function (windowClient) {
          return windowClient ? windowClient.focus() : null;
        });
      }
    }
    return self.clients.openWindow(target.href);
  }));
});
