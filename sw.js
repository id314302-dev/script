// Статика (озвучка, картинки, иконки) не меняется, поэтому берём её сначала из кэша: без связи, но при «живом» Wi-Fi запрос к сети висит минутами.
// Оболочка (index.html, cards.js, manifest) — сеть, но не дольше NET_WAIT мс, потом кэш; так новая версия подтягивается сразу, а офлайн приложение не ждёт.
importScripts("cards.js");   // даёт список колод DECKS, из него собираем файлы для кэша

const CACHE = "script-v1";   // префикс «script-»: на этом же адресе живёт ещё приложение «Карточки English» (кэши «cards-…»), чужие кэши не трогаем
const NET_WAIT = 2500;
const FILES = ["./", "index.html", "cards.js", "manifest.json", "sessions.json", "icon-v1-192.png", "icon-v1-512.png",
  ...DECKS.flatMap(d => d.cards.flatMap(c => [`audio/${d.dir}${c.id}.mp3`, `audio-uk/${d.dir}${c.id}.mp3`, ...(d.noimg ? [] : [`img/${d.dir}${c.id}.jpg`])]))];

// Докачивает недостающие файлы по 6 штук параллельно; отсутствующий на сервере файл (например, нет картинки) остальное не ломает
async function fill() {
  const c = await caches.open(CACHE);
  const todo = [];
  for (const f of FILES) if (!(await c.match(f))) todo.push(f);
  for (let i = 0; i < todo.length; i += 6) await Promise.allSettled(todo.slice(i, i + 6).map(f => c.add(f)));
}

self.addEventListener("install", e => {
  e.waitUntil(fill());
  self.skipWaiting();
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith("script-") && k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});
// Длинные тренировки (sessions/*.mp3, ~40 МБ) заранее не качаем: они сохраняются в кэш при первом воспроизведении.
// Страница просит докачать недостающее (если прошлая установка кэша оборвалась на слабой сети)
let filled = false;
self.addEventListener("message", e => {
  if (e.data === "precache" && !filled) { filled = true; e.waitUntil(fill()); }
});

const isAsset = u => /\/(audio|audio-uk|img|sessions)\//.test(u.pathname) || /\/icon-/.test(u.pathname);
const keep = (req, r) => { if (r && r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(req, copy)); } return r; };

function cacheFirst(req) {
  return caches.match(req).then(hit => hit || fetch(req).then(r => keep(req, r)));
}

function networkFirst(req) {
  return new Promise(resolve => {
    let done = false;
    const finish = r => { if (!done && r) { done = true; resolve(r); } };
    const timer = setTimeout(() => caches.match(req).then(finish), NET_WAIT);   // сеть молчит — отдаём копию
    fetch(req).then(r => { clearTimeout(timer); finish(keep(req, r)); })
      .catch(() => { clearTimeout(timer); caches.match(req).then(r => finish(r || Response.error())); });
  });
}

self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const u = new URL(e.request.url);
  if (u.origin !== location.origin) return;
  e.respondWith(isAsset(u) ? cacheFirst(e.request) : networkFirst(e.request));
});
