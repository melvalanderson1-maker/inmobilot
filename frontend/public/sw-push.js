self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  const d = event.data ? event.data.json() : {};
  event.waitUntil(
    (async () => {
      // Si la app está abierta y a la vista, ya suena el aviso interno
      const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      if (wins.some((w) => w.visibilityState === 'visible' && w.focused)) return;
      await self.registration.showNotification(d.titulo || 'Inmobilot', {
        body: d.mensaje || '',
        icon: '/favicon.ico',
        tag: d.tag,
        renotify: true,
        silent: false,
        data: { url: d.url || '/dashboard' },
      });
    })()
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/dashboard';
  event.waitUntil(
    (async () => {
      const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const w of wins) {
        await w.focus();
        try { await w.navigate(url); } catch (e) {}
        return;
      }
      await self.clients.openWindow(url);
    })()
  );
});