// ⚡ Service Worker for KOGM Sales Manager & Customer Portal - Khandelia Oil & General Mills
// Provides 10X faster app loading via aggressive caching & offline shell capability

const CACHE_NAME = 'kogm-sales-v9';
const STATIC_ASSETS = [
  '/',
  '/sale_manager',
  '/manifest.json',
  '/customer-manifest.json',
  '/images/icons/icon-192.png',
  '/images/icons/icon-512.png',
  '/images/icons/icon-maskable-512.png',
  '/images/Logo/3d_logo2.png',
  '/images/products/fauji-mustard-oil-1-litre-bottle.png',
  '/images/products/fauji-mustard-oil-1-litre-pouch.png',
  '/images/products/fauji-mustard-oil-15-kg-can.png',
  '/images/products/fauji-mustard-oil-15-kg-tin.png',
  '/images/products/fauji-mustard-oil-15-litre-tin.png',
  '/images/products/fauji-mustard-oil-500-ml-bottle.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-1-litre-bottle.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-1-litre-pouch.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-100-ml-bottle.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-15-kg-can.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-15-kg-tin.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-15-litre-can.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-15-litre-tin.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-2-litre-bottle.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-2-litre-can.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-200-ml-bottle.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-5-litre-can.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-500-ml-bottle.png',
  '/images/products/mashal-kachi-ghani-mustard-oil-500-ml-pouch.png',
  '/js/qrcode.min.js'
];

// Install: Cache critical assets
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Pre-caching static assets for 2X speed');
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.warn('[SW] Some assets could not be cached immediately:', err);
      });
    })
  );
});

// Activate: Clean old caches and claim clients immediately
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            console.log('[SW] Clearing old cache:', name);
            return caches.delete(name);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: Smart Caching Strategy
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // 1. Bypass non-GET requests immediately
  if (req.method !== 'GET') {
    return;
  }

  // 2. Bypass API calls and live data - Always fresh from network
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) {
    event.respondWith(fetch(req));
    return;
  }

  // 3. Static Assets (Images, Icons, JS, Fonts): Cache-First Strategy (Instant 2X Speed)
  if (
    url.pathname.startsWith('/images/') ||
    url.pathname.startsWith('/js/') ||
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com')
  ) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) {
          // Return cached version immediately, but fetch fresh in background
          fetch(req).then((fresh) => {
            if (fresh && fresh.status === 200) {
              caches.open(CACHE_NAME).then((c) => c.put(req, fresh));
            }
          }).catch(() => {});
          return cached;
        }
        return fetch(req).then((networkRes) => {
          if (networkRes && networkRes.status === 200) {
            const clone = networkRes.clone();
            caches.open(CACHE_NAME).then((c) => c.put(req, clone));
          }
          return networkRes;
        });
      })
    );
    return;
  }

  // 4. Navigation requests (/sale_manage, /): Network-first with cache fallback
  if (req.mode === 'navigate' || url.pathname === '/sale_manage') {
    event.respondWith(
      fetch(req)
        .then((networkRes) => {
          if (networkRes && networkRes.status === 200) {
            const clone = networkRes.clone();
            caches.open(CACHE_NAME).then((c) => c.put(req, clone));
          }
          return networkRes;
        })
        .catch(() => {
          return caches.match(req).then((cached) => {
            if (cached) return cached;
            return caches.match('/sale_manage');
          });
        })
    );
    return;
  }

  // Default: Stale-While-Revalidate
  event.respondWith(
    caches.match(req).then((cached) => {
      const fetchPromise = fetch(req).then((networkRes) => {
        if (networkRes && networkRes.status === 200) {
          const clone = networkRes.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, clone));
        }
        return networkRes;
      }).catch(() => null);

      return cached || fetchPromise;
    })
  );
});
