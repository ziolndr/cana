const $ = (selector) => document.querySelector(selector);
const list = $('#results');
const form = $('#searchForm');
const input = $('#query');
const typeSelect = $('#typeFilter');
const sentinel = $('#sentinel');
const connection = $('#connection');
const drawer = $('#drawer');
const drawerContent = $('#drawerContent');

const state = {
  q: '',
  type: 'all',
  offset: 0,
  limit: 50,
  total: 0,
  mode: 'loading',
  latency: null,
  seq: 0,
  searchController: null,
  pageController: null,
  searching: false,
  paging: false,
  done: false,
  frame: 0,
};

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function norm(value) {
  return String(value || '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function hashString(value) {
  let hash = 2166136261;
  for (const char of String(value)) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash >>> 0);
}

function scoreLabel(score) {
  return score == null ? '—' : Number(score).toFixed(3);
}

const imageExact = new Map();
const imageLineage = [];
const localPool = [];
const imageCache = new Map();

for (const item of IMAGE_REFERENCES) {
  for (const key of [item.name, ...(item.aliases || [])]) imageExact.set(norm(key), item);
  const canonical = norm(item.name);
  if (item.kind === 'bundled') localPool.push(item);
  if (!item.exact_only && canonical.split(' ').length > 1) imageLineage.push([canonical, item]);
}
imageLineage.sort((a, b) => b[0].length - a[0].length);

function localFallback(name) {
  const hash = hashString(name);
  const base = localPool[hash % localPool.length] || IMAGE_REFERENCES[0];
  return {
    ...base,
    relation: 'reference',
    cropX: 28 + (hash % 45),
    cropY: 30 + ((hash >>> 5) % 42),
    zoom: 1.02 + ((hash >>> 9) % 6) / 100,
  };
}

function imageForName(name) {
  const key = norm(name);
  const exact = imageExact.get(key);
  if (exact) return { ...exact, relation: 'exact', cropX: 50, cropY: 50, zoom: 1.02 };

  const hydrated = imageCache.get(key);
  if (hydrated) return { ...hydrated, relation: 'resolved', cropX: 50, cropY: 50, zoom: 1.02 };

  for (const [canonical, item] of imageLineage) {
    if (key.includes(canonical)) {
      return { ...item, relation: 'related', cropX: 50, cropY: 50, zoom: 1.02 };
    }
  }
  return localFallback(name);
}

function imageMarkup(image, name, eager = false) {
  const style = `--crop-x:${Number(image.cropX || 50)}%;--crop-y:${Number(image.cropY || 50)}%;--zoom:${Number(image.zoom || 1.02)}`;
  return `<img src="${esc(image.image)}" alt="Cannabis reference image for ${esc(name)}" loading="${eager ? 'eager' : 'lazy'}" decoding="async" style="${style}" data-image>`;
}

function lexicalPreview(query, type, limit = 50) {
  const phrase = norm(query);
  const terms = phrase.split(/\s+/).filter(Boolean);
  let rows = type === 'all' ? CATALOG : CATALOG.filter((row) => row.type === type);

  if (!terms.length) {
    const priority = new Map(IMAGE_REFERENCES.map((item, index) => [norm(item.name), index]));
    rows = [...rows]
      .sort((a, b) => {
        const ai = priority.has(norm(a.name)) ? priority.get(norm(a.name)) : 99999;
        const bi = priority.has(norm(b.name)) ? priority.get(norm(b.name)) : 99999;
        return ai - bi || a.name.localeCompare(b.name);
      })
      .map((row) => ({ ...row, score: null }));
    return { results: rows.slice(0, limit), total: rows.length, mode: 'field index', elapsed_ms: 0 };
  }

  const scored = rows.map((row) => {
    const name = norm(row.name);
    const kind = norm(row.type);
    let score = name === phrase ? 120 : name.startsWith(phrase) ? 72 : name.includes(phrase) ? 46 : 0;
    for (const term of terms) {
      if (name === term) score += 28;
      else if (name.startsWith(term)) score += 15;
      else if (name.includes(term)) score += 9;
      else if (kind.includes(term)) score += 2;
    }
    return [score, row];
  }).filter(([score]) => score > 0)
    .sort((a, b) => b[0] - a[0] || a[1].name.localeCompare(b[1].name));

  return {
    results: scored.slice(0, limit).map(([score, row]) => ({ ...row, score: Math.min(.999, .46 + score / 170) })),
    total: scored.length,
    mode: 'instant preview',
    elapsed_ms: 0,
  };
}

function setSearching(active, label) {
  state.searching = active;
  list.classList.toggle('is-pending', active);
  list.setAttribute('aria-busy', active ? 'true' : 'false');
  $('.live-state').classList.toggle('is-searching', active);
  $('#liveText').textContent = label || (active ? 'RANKING LIVE' : 'LIVE');
}

function updateMeta() {
  $('#count').textContent = Number(state.total || 0).toLocaleString();
  $('#queryLabel').textContent = state.q ? `FOR “${state.q.toUpperCase()}”` : 'RECORDS';
  $('#mode').textContent = String(state.mode || '').toUpperCase();
  $('#latency').textContent = state.latency == null ? '—' : `${Math.round(state.latency)} MS`;
}

function cardHTML(row, index, { offset = 0, seq = state.seq } = {}) {
  const rank = offset + index + 1;
  const image = imageForName(row.name);
  return `<article class="result-card" data-id="${esc(row.id)}" data-name="${esc(row.name)}" data-type="${esc(row.type || 'Unclassified')}" data-score="${esc(scoreLabel(row.score))}" data-seq="${seq}">
    <div class="card-image">
      ${imageMarkup(image, row.name, rank <= 12)}
      <span class="card-rank">${String(rank).padStart(2, '0')}</span>
      <span class="card-score">${scoreLabel(row.score)}</span>
      <div class="card-copy">
        <span class="card-type">${esc(row.type || 'Unclassified')}</span>
        <h2 class="card-name">${esc(row.name)}</h2>
        <span class="card-id">${esc(row.id)}</span>
      </div>
    </div>
    <button class="card-button" type="button" aria-label="Open ${esc(row.name)}"></button>
  </article>`;
}

function renderRows(rows, { replace = true, offset = 0, seq = state.seq } = {}) {
  if (replace) list.innerHTML = '';
  if (!rows.length) {
    if (replace) list.innerHTML = '<div class="empty">ARBITER IS RANKING THIS QUERY</div>';
    return;
  }
  list.insertAdjacentHTML('beforeend', rows.map((row, index) => cardHTML(row, index, { offset, seq })).join(''));
  hydrateRows(replace ? list : list.lastElementChild?.parentElement || list);
}

function applyResolvedImage(card, image) {
  if (!card || !image?.image) return;
  imageCache.set(norm(card.dataset.name), image);
  const frame = card.querySelector('.card-image');
  const old = frame.querySelector('img');
  const next = document.createElement('img');
  next.src = image.image;
  next.alt = `Cannabis reference image for ${card.dataset.name}`;
  next.loading = 'eager';
  next.decoding = 'async';
  next.style.setProperty('--crop-x', '50%');
  next.style.setProperty('--crop-y', '50%');
  next.style.setProperty('--zoom', '1.02');
  next.dataset.image = '';
  next.addEventListener('error', () => {}, { once: true });
  if (old) old.replaceWith(next);
  card.dataset.imageSource = image.source_url || '';
  card.dataset.imageCredit = image.source || 'Wikimedia Commons';
  card.dataset.imageLicense = image.license || 'See source';
}

const hydrationQueue = [];
let hydrationActive = 0;

function queueHydration(card) {
  if (!card || card.dataset.hydrating === '1' || card.dataset.hydrated === '1') return;
  const existing = imageForName(card.dataset.name);
  if (existing.relation === 'exact' || existing.relation === 'resolved') return;
  card.dataset.hydrating = '1';
  hydrationQueue.push(card);
  drainHydration();
}

function drainHydration() {
  while (hydrationActive < 5 && hydrationQueue.length) {
    const card = hydrationQueue.shift();
    if (!card?.isConnected) continue;
    hydrationActive += 1;
    fetch(`/api/image?name=${encodeURIComponent(card.dataset.name)}`, { cache: 'force-cache' })
      .then((response) => response.ok ? response.json() : null)
      .then((data) => {
        if (card.isConnected && data?.image) applyResolvedImage(card, data);
      })
      .catch(() => {})
      .finally(() => {
        card.dataset.hydrating = '0';
        card.dataset.hydrated = '1';
        hydrationActive -= 1;
        drainHydration();
      });
  }
}

function attachImageFallback(card) {
  card.querySelectorAll('img[data-image]').forEach((image) => {
    image.addEventListener('error', () => {
      const fallback = localFallback(card.dataset.name);
      image.src = fallback.image;
      image.style.setProperty('--crop-x', `${fallback.cropX}%`);
      image.style.setProperty('--crop-y', `${fallback.cropY}%`);
      image.style.setProperty('--zoom', fallback.zoom);
    }, { once: true });
  });
}

function hydrateRows(root) {
  root.querySelectorAll('.result-card').forEach((card, index) => {
    attachImageFallback(card);
    if (index < 16) queueHydration(card);
    else imageObserver.observe(card);
  });
}

const imageObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (entry.isIntersecting) {
      imageObserver.unobserve(entry.target);
      queueHydration(entry.target);
    }
  }
}, { rootMargin: '500px 0px' });

async function fetchSearch({ seq, offset = 0, controller }) {
  const started = performance.now();
  const response = await fetch('/api/search', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    signal: controller.signal,
    body: JSON.stringify({ q: state.q, type: state.type, offset, limit: state.limit }),
  });
  if (!response.ok) throw new Error('field unavailable');
  const data = await response.json();
  if (seq !== state.seq) throw new DOMException('stale', 'AbortError');
  data.elapsed_ms = data.elapsed_ms ?? performance.now() - started;
  return data;
}

function applyData(data, { replace, offset, seq }) {
  if (seq !== state.seq) return;
  const rows = data.results || [];
  state.total = Number(data.total || 0);
  state.mode = data.mode || 'ARBITER 72D';
  state.latency = data.elapsed_ms ?? null;
  renderRows(rows, { replace, offset, seq });
  state.offset = replace ? rows.length : offset + rows.length;
  state.done = rows.length < state.limit || state.offset >= state.total;
  updateMeta();
  if (!state.done) pageObserver.observe(sentinel);
}

async function runSearch(seq) {
  if (seq !== state.seq) return;
  state.q = input.value.trim();
  state.type = typeSelect.value;
  state.offset = 0;
  state.done = false;

  if (state.searchController) state.searchController.abort();
  if (state.pageController) state.pageController.abort();
  pageObserver.unobserve(sentinel);

  const preview = lexicalPreview(state.q, state.type, state.limit);
  if (preview.results.length || !state.q) {
    state.total = preview.total;
    state.mode = preview.mode;
    state.latency = 0;
    renderRows(preview.results, { replace: true, offset: 0, seq });
    updateMeta();
  }

  setSearching(true, 'RANKING LIVE');
  const controller = new AbortController();
  state.searchController = controller;
  try {
    const data = await fetchSearch({ seq, offset: 0, controller });
    applyData(data, { replace: true, offset: 0, seq });
    setSearching(false, 'LIVE RESULT');
  } catch (error) {
    if (error.name === 'AbortError') return;
    connection.textContent = 'LOCAL INDEX · ARBITER OFFLINE';
    setSearching(false, 'LOCAL RESULT');
  }
}

function requestSearch() {
  state.seq += 1;
  const seq = state.seq;
  if (state.searchController) state.searchController.abort();
  if (state.pageController) state.pageController.abort();
  cancelAnimationFrame(state.frame);
  state.frame = requestAnimationFrame(() => runSearch(seq));
}

async function loadNextPage() {
  if (state.searching || state.paging || state.done) return;
  state.paging = true;
  pageObserver.unobserve(sentinel);
  const seq = state.seq;
  const offset = state.offset;
  const controller = new AbortController();
  state.pageController = controller;
  $('#loading').hidden = false;
  try {
    const data = await fetchSearch({ seq, offset, controller });
    applyData(data, { replace: false, offset, seq });
  } catch (error) {
    if (error.name !== 'AbortError') state.done = true;
  } finally {
    state.paging = false;
    $('#loading').hidden = true;
  }
}

const pageObserver = new IntersectionObserver((entries) => {
  if (entries.some((entry) => entry.isIntersecting)) loadNextPage();
}, { rootMargin: '320px 0px' });

function openCard(card) {
  const image = imageForName(card.dataset.name);
  const relation = image.relation === 'exact' || image.relation === 'resolved'
    ? 'MATCHED OPEN IMAGE'
    : 'OPEN CANNABIS REFERENCE IMAGE';
  const sourceUrl = card.dataset.imageSource || image.source_url || '#';
  const source = card.dataset.imageCredit || image.source || 'Open reference';
  const license = card.dataset.imageLicense || image.license || 'See source';
  drawerContent.innerHTML = `<div class="drawer-photo">${imageMarkup(image, card.dataset.name, true)}</div>
    <div class="drawer-body">
      <div class="drawer-kicker">${esc(relation)} · ${esc(card.dataset.type)}</div>
      <h2>${esc(card.dataset.name)}</h2>
      <p>Ranked from the CANA field by the language of the current query. The strain name is an identity layer; tested batch chemistry, dose, format, and context remain the production truth.</p>
      <div class="drawer-data">
        <div class="drawer-row"><span>RECORD</span><strong>${esc(card.dataset.id)}</strong></div>
        <div class="drawer-row"><span>RESONANCE</span><strong>${esc(card.dataset.score)}</strong></div>
        <div class="drawer-row"><span>IMAGE</span><strong>${esc(source)}</strong></div>
        <div class="drawer-row"><span>LICENSE</span><strong>${esc(license)}</strong></div>
      </div>
      ${sourceUrl !== '#' ? `<a class="drawer-source" href="${esc(sourceUrl)}" target="_blank" rel="noopener"><span>OPEN IMAGE SOURCE</span><span>↗</span></a>` : ''}
    </div>`;
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
}

function closeDrawer() {
  drawer.classList.remove('open');
  drawer.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  requestSearch();
});
input.addEventListener('input', (event) => {
  if (!event.isComposing) requestSearch();
});
input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    requestSearch();
  }
});
typeSelect.addEventListener('change', requestSearch);
document.querySelectorAll('[data-query]').forEach((button) => button.addEventListener('click', () => {
  input.value = button.dataset.query || '';
  input.focus();
  requestSearch();
}));
list.addEventListener('click', (event) => {
  const card = event.target.closest('.result-card');
  if (card) openCard(card);
});
drawer.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', closeDrawer));
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && drawer.classList.contains('open')) closeDrawer();
});

async function readManifest() {
  try {
    const response = await fetch('/api/manifest', { cache: 'no-store' });
    if (!response.ok) throw new Error();
    const manifest = await response.json();
    connection.textContent = `${Number(manifest.count || 0).toLocaleString()} RECORDS · ${manifest.field_ready ? 'ARBITER 72D LIVE' : 'LOCAL INDEX'}`;
  } catch (_) {
    connection.textContent = 'LOCAL INDEX';
  }
}

readManifest();
requestSearch();
