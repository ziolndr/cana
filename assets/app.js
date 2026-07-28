const $ = (selector) => document.querySelector(selector);

const list = $('#results');
const form = $('#searchForm');
const input = $('#query');
const categorySelect = $('#typeFilter');
const sentinel = $('#sentinel');
const connection = $('#connection');
const drawer = $('#drawer');
const drawerContent = $('#drawerContent');

const state = {
  products: [],
  vectors: null,
  count: 0,
  dim: 72,
  useFreq: true,
  embedUrls: [],
  seq: 0,
  q: '',
  category: 'all',
  ranked: [],
  offset: 0,
  limit: 50,
  latency: null,
  mode: 'LOADING',
  searching: 0,
};

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]));
}

function normalize(value) {
  return String(value || '').trim().toLowerCase();
}

function productImage(row) {
  let image = row.image || row.image_url || row.asset || row.photo || '';
  if (!image && row.image_filename) image = `/assets/inventory/${row.image_filename}`;
  if (image && !image.startsWith('/') && !/^https?:\/\//i.test(image)) {
    image = image.includes('/') ? `/${image.replace(/^\.?\//, '')}` : `/assets/inventory/${image}`;
  }
  return image;
}

function productCategory(row) {
  return row.category || row.type || row.format || 'Uncategorized';
}

function productSubtype(row) {
  return row.subcategory || row.subtype || row.product_type || row.format || '';
}

function money(value) {
  if (value == null || value === '') return '';
  const numeric = Number(String(value).replace(/[^0-9.-]/g, ''));
  return Number.isFinite(numeric) ? `$${numeric.toFixed(2)}` : String(value);
}

function setSearching(active) {
  state.searching += active ? 1 : -1;
  state.searching = Math.max(0, state.searching);
  const busy = state.searching > 0;
  list.classList.toggle('is-pending', busy);
  list.setAttribute('aria-busy', busy ? 'true' : 'false');
  $('.live-state').classList.toggle('is-searching', busy);
  $('#liveText').textContent = busy ? 'RANKING LIVE' : 'LIVE RESULT';
}

function updateMeta() {
  $('#count').textContent = Number(state.count || 0).toLocaleString();
  $('#queryLabel').textContent = state.q ? `FOR “${state.q.toUpperCase()}”` : 'PRODUCTS';
  $('#mode').textContent = state.mode;
  $('#latency').textContent = state.latency == null ? '—' : `${Math.round(state.latency)} MS`;
}

function cardHTML(entry, position) {
  const row = entry.row;
  const rank = position + 1;
  const image = productImage(row);
  const category = productCategory(row);
  const subtype = productSubtype(row);
  const score = entry.score == null ? '—' : Number(entry.score).toFixed(3);
  const brand = row.brand || row.vendor || '';
  const price = money(row.price);
  const kicker = [brand, category, subtype].filter(Boolean).join(' · ');

  return `<article class="result-card"
      data-index="${entry.index}"
      data-score="${esc(score)}">
    <div class="card-image">
      ${image
        ? `<img src="${esc(image)}" alt="${esc(row.name || 'Cannabis product')} product image"
             loading="${rank <= 12 ? 'eager' : 'lazy'}" decoding="async">`
        : ''}
      <span class="card-rank">${String(rank).padStart(2, '0')}</span>
      <span class="card-score">${esc(score)}</span>
      <div class="card-copy">
        <span class="card-type">${esc(kicker || 'IN STOCK SNAPSHOT')}</span>
        <h2 class="card-name">${esc(row.name || row.title || 'Untitled product')}</h2>
        <span class="card-id">${esc([price, category, subtype].filter(Boolean).join(' · '))}</span>
      </div>
    </div>
    <button class="card-button" type="button"
      aria-label="Open ${esc(row.name || row.title || 'product')}"></button>
  </article>`;
}

function renderPage() {
  const page = state.ranked.slice(0, state.offset + state.limit);
  if (!page.length) {
    list.innerHTML = '<div class="empty">NO PRODUCTS MATCH THIS INVENTORY FILTER</div>';
    return;
  }
  list.innerHTML = page.map((entry, index) => cardHTML(entry, index)).join('');
}

function initialRanking() {
  const category = normalize(state.category);
  const ranked = [];
  for (let index = 0; index < state.products.length; index += 1) {
    const row = state.products[index];
    if (category !== 'all' && normalize(productCategory(row)) !== category) continue;
    ranked.push({ index, row, score: null });
  }
  return ranked;
}

function parseVectorResponse(data) {
  let vectors = data?.vectors || data?.embeddings || data?.data;
  if (vectors && !Array.isArray(vectors) && typeof vectors === 'object') {
    vectors = vectors.vectors || vectors.embeddings || vectors.data;
  }
  let first = Array.isArray(vectors) ? vectors[0] : null;
  if (first && !Array.isArray(first) && typeof first === 'object') {
    first = first.embedding || first.vector;
  }
  if (!Array.isArray(first) && Array.isArray(data?.embedding)) first = data.embedding;
  if (!Array.isArray(first) && Array.isArray(data?.vector)) first = data.vector;
  if (!Array.isArray(first) || first.length !== state.dim) {
    throw new Error(`ARBITER returned ${Array.isArray(first) ? first.length : 'no'} dimensions`);
  }
  const out = new Float32Array(first);
  let norm = 0;
  for (let i = 0; i < out.length; i += 1) norm += out[i] * out[i];
  norm = Math.sqrt(norm) || 1;
  for (let i = 0; i < out.length; i += 1) out[i] /= norm;
  return out;
}

async function embedDirect(query) {
  let lastError = null;
  for (const url of state.embedUrls) {
    try {
      const response = await fetch(url, {
        method: 'POST',
        mode: 'cors',
        cache: 'no-store',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ texts: [query], use_freq: state.useFreq }),
      });
      if (!response.ok) throw new Error(`${response.status} from ${url}`);
      return parseVectorResponse(await response.json());
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error('No direct ARBITER endpoint is configured');
}

function rankVector(queryVector) {
  const category = normalize(state.category);
  const ranked = [];
  const vectors = state.vectors;
  const dim = state.dim;

  for (let index = 0; index < state.products.length; index += 1) {
    const row = state.products[index];
    if (category !== 'all' && normalize(productCategory(row)) !== category) continue;

    const base = index * dim;
    let score = 0;
    for (let axis = 0; axis < dim; axis += 1) {
      score += vectors[base + axis] * queryVector[axis];
    }
    ranked.push({ index, row, score });
  }

  ranked.sort((a, b) => b.score - a.score || a.index - b.index);
  return ranked;
}

async function serverFallback(query, requestId, started) {
  const response = await fetch('/api/search', {
    method: 'POST',
    cache: 'no-store',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      q: query,
      category: state.category,
      type: state.category,
      offset: 0,
      limit: state.limit,
    }),
  });
  if (!response.ok) throw new Error(`same-origin search returned ${response.status}`);
  const data = await response.json();
  if (requestId !== state.seq) return;

  const results = data.results || [];
  state.ranked = results.map((row, index) => ({
    index,
    row,
    score: row.score ?? null,
  }));
  state.count = Number(data.total ?? results.length);
  state.offset = state.limit;
  state.latency = data.elapsed_ms ?? performance.now() - started;
  state.mode = data.mode || 'ARBITER 72D';
  renderPage();
  updateMeta();
}

async function runSearch() {
  const requestId = ++state.seq;
  const query = input.value.trim();
  state.q = query;
  state.category = categorySelect.value;
  state.offset = state.limit;

  if (!query) {
    state.ranked = initialRanking();
    state.count = state.ranked.length;
    state.latency = 0;
    state.mode = 'LOCAL 72D FIELD';
    renderPage();
    updateMeta();
    return;
  }

  // Every input event starts a genuine embedding request immediately.
  // Requests are never debounced, coalesced, or canceled.
  setSearching(true);
  const started = performance.now();

  try {
    const queryVector = await embedDirect(query);
    if (requestId !== state.seq) return;

    state.ranked = rankVector(queryVector);
    state.count = state.ranked.length;
    state.latency = performance.now() - started;
    state.mode = 'ARBITER 72D · BROWSER RANK';
    renderPage();
    updateMeta();
  } catch (directError) {
    try {
      await serverFallback(query, requestId, started);
    } catch (fallbackError) {
      if (requestId === state.seq) {
        connection.textContent = 'FIELD READY · QUERY EMBED OFFLINE';
        state.mode = 'QUERY EMBED OFFLINE';
        state.latency = performance.now() - started;
        updateMeta();
      }
      console.error('Direct ARBITER failed:', directError);
      console.error('Fallback search failed:', fallbackError);
    }
  } finally {
    setSearching(false);
  }
}

function populateCategories() {
  const categories = [...new Set(state.products.map(productCategory).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
  categorySelect.innerHTML = '<option value="all">ALL CATEGORIES</option>' +
    categories.map((category) =>
      `<option value="${esc(category)}">${esc(category).toUpperCase()}</option>`
    ).join('');
}

function openCard(card) {
  const index = Number(card.dataset.index);
  const row = state.products[index];
  if (!row) return;

  const image = productImage(row);
  const name = row.name || row.title || 'Untitled product';
  const category = productCategory(row);
  const subtype = productSubtype(row);
  const brand = row.brand || row.vendor || '';
  const price = money(row.price);
  const description = row.description || row.profile || row.experience || '';
  const sourceUrl = row.url || row.source_url || row.product_url || '';

  drawerContent.innerHTML = `<div class="drawer-photo">
      ${image ? `<img src="${esc(image)}" alt="${esc(name)} product image">` : ''}
    </div>
    <div class="drawer-body">
      <div class="drawer-kicker">IN STOCK SNAPSHOT · ${esc(category)}</div>
      <h2>${esc(name)}</h2>
      ${description ? `<p>${esc(description)}</p>` : ''}
      <div class="drawer-data">
        <div class="drawer-row"><span>BRAND</span><strong>${esc(brand || '—')}</strong></div>
        <div class="drawer-row"><span>PRICE</span><strong>${esc(price || '—')}</strong></div>
        <div class="drawer-row"><span>CATEGORY</span><strong>${esc(category)}</strong></div>
        <div class="drawer-row"><span>FORMAT</span><strong>${esc(subtype || '—')}</strong></div>
        <div class="drawer-row"><span>RESONANCE</span><strong>${esc(card.dataset.score)}</strong></div>
      </div>
      ${sourceUrl
        ? `<a class="drawer-source" href="${esc(sourceUrl)}" target="_blank" rel="noopener">
             <span>OPEN PRODUCT</span><span>↗</span>
           </a>`
        : ''}
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

async function getJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

async function initialize() {
  const [browserManifest, products, vectorBuffer, health, apiManifest] = await Promise.all([
    getJson('/field/browser_field.json'),
    getJson('/data/browser_products.json'),
    fetch('/field/browser_vectors.f32', { cache: 'force-cache' }).then((response) => {
      if (!response.ok) throw new Error(`vector field returned ${response.status}`);
      return response.arrayBuffer();
    }),
    getJson('/health').catch(() => ({})),
    getJson('/api/manifest').catch(() => ({})),
  ]);

  state.products = products;
  state.count = Number(browserManifest.count || products.length);
  state.dim = Number(browserManifest.dim || 72);
  state.useFreq = browserManifest.use_freq !== false;
  state.vectors = new Float32Array(vectorBuffer);

  if (state.products.length !== state.count) {
    throw new Error(`Product count ${state.products.length} does not match ${state.count}`);
  }
  if (state.vectors.length !== state.count * state.dim) {
    throw new Error(`Vector length ${state.vectors.length} does not match ${state.count} × ${state.dim}`);
  }

  const candidates = [
    health.fast_embed_url,
    apiManifest.fast_embed_url,
    health.embed_url,
    apiManifest.embed_url,
    browserManifest.embed_url,
  ].filter(Boolean);

  state.embedUrls = [...new Set(candidates)]
    .filter((url) => !url.includes('cana-embed.actualgeneralintelligence.com'));

  populateCategories();
  state.ranked = initialRanking();
  state.offset = state.limit;
  state.count = state.ranked.length;
  state.mode = 'LOCAL 72D FIELD';
  state.latency = 0;
  renderPage();
  updateMeta();

  connection.textContent =
    `${Number(browserManifest.count).toLocaleString()} PRODUCTS · 72D · FIELD READY · ` +
    (state.embedUrls.length ? 'QUERY EMBED ONLINE' : 'QUERY EMBED FALLBACK');

  input.focus();
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  runSearch();
});

input.addEventListener('input', (event) => {
  if (!event.isComposing) runSearch();
});

input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    runSearch();
  }
});

categorySelect.addEventListener('change', runSearch);

document.querySelectorAll('[data-query]').forEach((button) => {
  button.addEventListener('click', () => {
    input.value = button.dataset.query || '';
    input.focus();
    runSearch();
  });
});

list.addEventListener('click', (event) => {
  const card = event.target.closest('.result-card');
  if (card) openCard(card);
});

drawer.querySelectorAll('[data-close]').forEach((button) => {
  button.addEventListener('click', closeDrawer);
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && drawer.classList.contains('open')) closeDrawer();
});

const pageObserver = new IntersectionObserver((entries) => {
  if (!entries.some((entry) => entry.isIntersecting)) return;
  if (state.offset >= state.ranked.length) return;
  state.offset += state.limit;
  renderPage();
}, { rootMargin: '320px 0px' });

pageObserver.observe(sentinel);

initialize().catch((error) => {
  console.error(error);
  connection.textContent = 'FIELD LOAD FAILED';
  list.innerHTML = `<div class="empty">${esc(error.message)}</div>`;
});
