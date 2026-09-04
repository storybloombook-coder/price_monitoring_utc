const byId = id => document.getElementById(id);
const uiText = value => window.pmI18n?.t(String(value ?? '')) ?? String(value ?? '');
const uiLocale = () => window.pmI18n?.locale || 'en-GB';
const HIDDEN_COLUMNS_KEY = 'price-monitor-v5.hidden-columns';
const RUN_MODE_KEY = 'price-monitor-v5.run-mode';
const RUN_MODE_HELP = {
  quick: 'Quick · reuse complete automatic marketplace results for up to 12 hours. Mode changes cache age only, not collection methods.',
  balanced: 'Balanced · reuse complete automatic marketplace results for up to 4 hours. Manual decisions are not reused as fresh prices. Mode changes cache age only.',
  deep: 'Deep · ignore the price cache and check again. The same collection methods and protection cooldowns still apply.'
};
const SHOP_METHODS = [
  ['auto', 'Auto · gentle fallback'], ['direct', 'Direct request'], ['background', 'Background Edge'],
  ['playwright', 'Playwright Edge'], ['extension', 'Browser extension'], ['manual', 'Manual discovery · saved links auto']
];
const MARKETPLACE_METHODS = [['auto', 'Auto'], ['legacy', 'Legacy engine']];
const ASSISTED_MARKETPLACE_METHODS = [['auto', 'Assisted · Edge + manual']];
const STATUS_HELP = {
  active: 'Enabled and available for the normal workflow.',
  paused: 'Temporarily excluded from monitoring without deleting the position.',
  trash: 'Moved to trash. It is excluded until restored or permanently deleted.',
  monitoring: 'This stock model is linked to an active model in the monitoring list.',
  unmatched: 'This stock position is not linked to an active monitoring model.',
  success: 'An exact model match returned a usable price and a link to the offer.',
  failed: 'The check ended with an error and returned no reliable result.',
  'not-found': 'The source was checked, but no matching model or offer was found.',
  incomplete: 'The check was stopped or could not finish with a reliable result.',
  'action-required': 'A person must verify the page, retry capture, or confirm the result manually.',
  cooldown: 'Requests to this source are paused temporarily to avoid a longer block.',
  cached: 'A recent saved result was reused; no new retailer request was sent.',
  running: 'The check is currently running.',
  pending: 'The check is queued and has not finished yet.',
  'not-started': 'This check has not started.',
  disabled: 'This source is switched off and is not included in monitoring.'
};
STATUS_HELP['not-listed'] = 'The completed marketplace pages did not list this shop. This does not mean the shop has no stock.';
STATUS_HELP.unverified = 'Not verified: one or more marketplace checks are pending, blocked, stopped or incomplete. This is NOT Not found; no conclusion about this shop is possible yet.';
const SEARCH_FALLBACK_HELP = ' On every marketplace, if the original SKU is not found, search again with one, then two trailing characters removed (minimum 3 characters, letters and digits). Known S45HE/S45H, S55HE/S55H and Q75HE/Q75H aliases are accepted; other plausible variants go to Quick Review. Unrelated prefix matches are rejected.';
const PARSING_HELP = {
  kaina24: 'Search TCL + model, then read current seller rows on the Kaina24 comparison page. Cash price and per-seller availability are read separately; delivery, installments, duplicate ads and sold-out history are excluded. Senukai uses its displayed SMART NET loyalty price. Saved comparison links are tried first. No retailer pages are opened; protection pauses requests.',
  hinnavaatlus: 'Search TCL + model and read seller offers on the matching comparison page. One timeout is retried automatically. S45HE/S45H, S55HE/S55H and Q75HE/Q75H are explicit aliases; false prefix candidates are rejected and plausible variants go to Quick Review. Delivery time alone does not confirm stock. No retailer pages are opened.',
  salidzini: 'Auto uses one active Chrome or Edge extension at a time. A safe browser cycle checks 5, pauses, checks 5, pauses, then checks 10. CAPTCHA or two blank pages starts a protective cooldown; use Test Salidzini session before continuing or switch to the connected standby browser. No parallel requests, CAPTCHA solving or retailer-page visits.'
};
function parsingInfo(key, label = key) {
  const help = PARSING_HELP[key] ? [PARSING_HELP[key], SEARCH_FALLBACK_HELP].map(uiText).join('') : null;
  return help ? `<span class="parsing-info"><button type="button" class="info-button" aria-label="${escapeHtml(uiText('How this marketplace is collected'))}" aria-describedby="parsing-${escapeHtml(key)}">i</button><span role="tooltip" id="parsing-${escapeHtml(key)}">${escapeHtml(help)}</span></span>` : '';
}
STATUS_HELP.cached = 'A recent marketplace observation was reused. Its original collection time is preserved.';
const state = {
  source: [], sourceOptions: [], stock: [], summary: null, sources: [], tasks: [], shopResults: [], runPoll: null,
  catalogStates: { source: new Set(['active', 'paused']), stock: new Set(['active', 'paused']) },
  resultFilters: { model: new Set(), status: new Set(), marketplace: new Set(), shop: new Set() },
  resultFilterKnown: { model: new Set(), status: new Set(), marketplace: new Set(), shop: new Set() },
  resultFilterInitialized: false,
  currentRunId: null, lastActionSignature: '', actionRenderSignature: '', actionItems: [], stopRequested: false,
  historyLoading: false, resultRenderSignature: '', lastRunStatus: '', modelFilterQuery: '',
  hiddenColumns: new Set(JSON.parse(localStorage.getItem(HIDDEN_COLUMNS_KEY) || '[]'))
};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(uiText(data?.detail || data || `Request failed (${response.status})`));
  return data;
}

function showBanner(kind, message) {
  const error = byId('error-banner');
  const success = byId('success-banner');
  error.hidden = true; success.hidden = true;
  if (!message) return;
  const target = kind === 'error' ? error : success;
  target.textContent = uiText(message); target.hidden = false;
  window.setTimeout(() => { target.hidden = true; }, 5000);
}

const COPY_ICON = '<svg viewBox="0 0 24 24"><rect x="8" y="8" width="10" height="11" rx="2"></rect><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h2"></path></svg>';
const CHECK_ICON = '<svg viewBox="0 0 24 24"><path d="m6 12 4 4 8-9"></path></svg>';
function copyModelButton(model = '') {
  return `<button type="button" class="copy-model-button" data-copy-model="${escapeHtml(model)}" title="Copy the model name to the clipboard" aria-label="Copy the model name to the clipboard">${COPY_ICON}</button>`;
}
async function copyModel(button) {
  const input = button.dataset.copyInput ? byId(button.dataset.copyInput) : null;
  const value = String(input?.value || button.dataset.copyModel || '').trim();
  if (!value) return showBanner('error', 'There is no model name to copy.');
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
    else {
      const fallback = document.createElement('textarea'); fallback.value = value;
      fallback.style.position = 'fixed'; fallback.style.opacity = '0'; document.body.appendChild(fallback);
      fallback.select(); document.execCommand('copy'); fallback.remove();
    }
    const original = button.innerHTML; button.classList.add('copied'); button.innerHTML = CHECK_ICON;
    window.setTimeout(() => { button.classList.remove('copied'); button.innerHTML = original; }, 1600);
  } catch (error) { showBanner('error', uiText(`Could not copy the model: ${error.message}`)); }
}

function badge(label, type, help = STATUS_HELP[type]) {
  const tooltip = help ? ` title="${escapeHtml(help)}" tabindex="0"` : '';
  return `<span class="badge ${escapeHtml(type)}"${tooltip}>${escapeHtml(label)}</span>`;
}
function statusClass(value) { return String(value || '').toLowerCase().replaceAll('_', '-'); }
function formatDuration(seconds) {
  const value = Math.max(0, Math.round(Number(seconds) || 0));
  if (value < 60) return `${value}s`;
  const hours = Math.floor(value / 3600); const minutes = Math.ceil((value % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}
function updateRunModeHelp() {
  const mode = byId('run-mode').value;
  localStorage.setItem(RUN_MODE_KEY, mode);
  byId('run-mode-help').textContent = RUN_MODE_HELP[mode] || RUN_MODE_HELP.balanced;
  byId('cache-summary').textContent = mode === 'deep' ? '· fresh checks' : `· cache up to ${mode === 'quick' ? 12 : 4} hours`;
}

function updateFileName(input) {
  const target = byId(`${input.id}-name`);
  if (target) target.textContent = input.files?.[0]?.name || 'No file selected';
}

function itemStatus(item) {
  if (item.state === 'trash') return badge('Trash', 'trash');
  if (item.paused) return badge('Paused', 'paused');
  return badge('Active', 'active');
}

function actionButtons(item) {
  if (item.state === 'trash') return `<button class="link-action" data-action="restore" data-id="${item.id}">Restore</button>
    <button class="link-action danger" data-action="delete-permanently" data-id="${item.id}">Delete permanently</button>`;
  return `<button class="link-action" data-action="edit" data-id="${item.id}">Edit</button>
    <button class="link-action" data-action="pause" data-id="${item.id}">${item.paused ? 'Resume' : 'Pause'}</button>
    <button class="link-action danger" data-action="trash" data-id="${item.id}">Trash</button>`;
}

function filteredCatalog(kind) { return state[kind].filter(item => state.catalogStates[kind].has(item.state)); }

function renderSource() {
  const items = filteredCatalog('source');
  byId('source-rows').innerHTML = items.length ? items.map(item => `<tr>
    <td><span class="item-primary">${escapeHtml(item.model)}</span><span class="item-secondary">${escapeHtml(item.origin)}</span></td>
    <td>${escapeHtml((item.source_sheets || []).join(', ') || 'TV')}</td><td>${itemStatus(item)}</td><td>${actionButtons(item)}</td></tr>`).join('')
    : '<tr><td colspan="4" class="empty">No positions found.</td></tr>';
}

function renderStock() {
  const items = filteredCatalog('stock');
  byId('stock-rows').innerHTML = items.length ? items.map(item => `<tr class="${item.matched ? 'stock-row-monitored' : ''}"><td><div class="stock-position">${item.state === 'trash' ? '' : item.matched ? '<span class="monitor-linked" title="In monitoring" aria-label="In monitoring">✓</span>' : `<button class="monitor-arrow" data-action="monitor" data-id="${item.id}" title="Add to monitoring" aria-label="Add ${escapeHtml(item.model || item.nomenclature)} to monitoring">←</button>`}<span><span class="item-primary">${escapeHtml(item.nomenclature)}</span>
    <span class="item-secondary">${escapeHtml(item.model || 'No linked model')} · ${escapeHtml(item.warehouse || 'No warehouse')}</span></span></div></td>
    <td>${Number(item.quantity || 0).toLocaleString(uiLocale())} units<span class="item-secondary">${Number(item.unit_cost_eur || 0).toFixed(2)} EUR</span></td>
    <td>${itemStatus(item)} ${item.state !== 'trash' && item.matched ? badge('In monitoring', 'monitoring') : item.state !== 'trash' ? badge('Unmatched', 'unmatched') : ''}</td><td>${actionButtons(item)}</td></tr>`).join('')
    : '<tr><td colspan="4" class="empty">No positions found.</td></tr>';
}

function renderSummary() {
  if (!state.summary) return;
  const s = state.summary.source; const w = state.summary.stock;
  byId('catalog-summary').textContent = `Monitoring: ${s.active} active, ${s.paused} paused · Stock: ${w.active} active, ${w.unmatched} unmatched`;
  byId('source-model-options').innerHTML = state.sourceOptions.filter(item => item.state !== 'trash').map(item => `<option value="${escapeHtml(item.model)}"></option>`).join('');
}

function renderMultiFilter(id, options, selected, onChange, emptyText = 'No options', searchable = false) {
  const root = byId(id); const menu = root.querySelector('.filter-menu');
  const search = searchable ? `<input class="filter-search" type="search" value="${escapeHtml(root.dataset.query || '')}" placeholder="Search models…" aria-label="Search models">` : '';
  menu.innerHTML = options.length ? `${search}<div class="filter-options">${options.map(option => `<label><input type="checkbox" value="${escapeHtml(option.value)}" ${selected.has(option.value) ? 'checked' : ''}> ${escapeHtml(option.label)}</label>`).join('')}</div>` : `<span class="muted">${emptyText}</span>`;
  menu.querySelectorAll('input[type="checkbox"]').forEach(input => input.addEventListener('change', () => {
    if (input.checked) selected.add(input.value); else selected.delete(input.value);
    root.querySelector('summary').dataset.count = selected.size;
    onChange();
  }));
  const searchInput = menu.querySelector('.filter-search');
  if (searchInput) searchInput.addEventListener('input', () => {
    root.dataset.query = searchInput.value;
    const query = searchInput.value.trim().toLocaleLowerCase();
    menu.querySelectorAll('.filter-options label').forEach(label => { label.hidden = Boolean(query) && !label.textContent.toLocaleLowerCase().includes(query); });
  });
}

function initializeCatalogFilters() {
  const options = [{ value: 'active', label: 'Active' }, { value: 'paused', label: 'Paused' }, { value: 'trash', label: 'Trash' }];
  renderMultiFilter('source-state-filter', options, state.catalogStates.source, renderSource);
  renderMultiFilter('stock-state-filter', options, state.catalogStates.stock, renderStock);
}

async function loadKind(kind) {
  const query = byId(`${kind}-search`).value.trim();
  state[kind] = await api(`/catalog/items?kind=${kind}&scope=all&q=${encodeURIComponent(query)}`);
  if (kind === 'source') renderSource(); else renderStock();
}

async function loadCatalog() {
  const [summary, sourceOptions] = await Promise.all([api('/catalog/summary'), api('/catalog/items?kind=source&scope=active'), loadKind('source'), loadKind('stock')]);
  state.summary = summary; state.sourceOptions = sourceOptions; renderSummary();
}

function sourceSwitch(item) {
  const identity = item.kind === 'marketplace' ? `<span class="source-title"><a href="${escapeHtml(item.base_url)}" target="_blank" rel="noopener">${escapeHtml(item.name)}</a>${parsingInfo(item.key, item.name)}</span>` : `<span>${escapeHtml(item.name)}</span>`;
  return `<div class="source-item ${item.master_enabled ? '' : 'master-disabled'}"><div class="source-identity">${identity}<span class="learned-method">${item.kind === 'shop' ? 'Seller filter · no direct requests' : 'Comparison pages only'}</span></div>
    <div class="source-controls">
    ${item.key === 'salidzini' ? `<label class="salidzini-mode">Collection <select id="salidzini-mode" aria-label="Salidzini collection mode"><option value="auto" ${state.salidziniMode !== 'manual' ? 'selected' : ''}>Auto</option><option value="manual" ${state.salidziniMode === 'manual' ? 'selected' : ''}>Manual</option></select></label>` : ''}
    <label class="switch-row" aria-label="Enable ${escapeHtml(item.name)}"><input type="checkbox" data-source-key="${escapeHtml(item.key)}" ${item.enabled ? 'checked' : ''} ${item.master_enabled ? '' : 'disabled'}><span class="switch"></span></label></div></div>`;
}

function renderSources() {
  const marketplaces = state.sources.filter(item => item.kind === 'marketplace');
  const shops = state.sources.filter(item => item.kind === 'shop');
  byId('marketplace-master').checked = marketplaces[0]?.master_enabled ?? true;
  byId('shop-master').checked = shops[0]?.master_enabled ?? true;
  byId('marketplace-count').textContent = `${marketplaces.filter(s => s.effective_enabled).length} of ${marketplaces.length} enabled`;
  byId('shop-count').textContent = `${shops.filter(s => s.effective_enabled).length} of ${shops.length} seller filters enabled`;
  byId('marketplace-list').innerHTML = marketplaces.map(sourceSwitch).join('');
  const countries = ['Lithuania', 'Latvia', 'Estonia'];
  byId('shop-list').innerHTML = countries.map(country => {
    const items = shops.filter(item => item.country === country);
    return `<div class="country-block"><span class="country-name">${country}</span><div class="country-shops">${items.length ? items.map(sourceSwitch).join('') : '<span class="muted">No shops configured yet.</span>'}</div></div>`;
  }).join('');
  byId('shop-link-inputs').innerHTML = '';
  byId('marketplace-link-inputs').innerHTML = marketplaces.map(item => `<label><a href="${escapeHtml(item.base_url)}" target="_blank" rel="noopener">${escapeHtml(item.name)} ↗</a><input data-marketplace-link="${escapeHtml(item.key)}" type="url" placeholder="${escapeHtml(item.base_url)}comparison or search…"></label>`).join('');
  document.querySelectorAll('[data-source-key]').forEach(input => input.addEventListener('change', () => updateSource(input.dataset.sourceKey, input.checked)));
  document.querySelectorAll('[data-source-method]').forEach(select => select.addEventListener('change', () => updateSourceMethod(select.dataset.sourceMethod, select.value)));
  document.querySelectorAll('[data-test-source]').forEach(button => button.addEventListener('click', () => openMethodTest(button.dataset.testSource)));
  byId('salidzini-mode')?.addEventListener('change', async event => {
    const select = event.target; select.disabled = true;
    try {
      const result = await api('/salidzini/settings', {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify({mode:select.value})});
      state.salidziniMode = result.mode;
      state.actionRenderSignature = '';
      if (state.currentRunId) await pollRun(state.currentRunId);
      showBanner('success', `Salidzini ${result.mode === 'auto' ? 'Auto: connected v5.0.8+ extension required' : 'Manual: no automatic requests'}. Applies to new checks; existing results stay unchanged.`);
    } catch (error) { select.value = state.salidziniMode; showBanner('error', error.message); }
    finally { select.disabled = false; }
  });
}

async function loadSources() {
  const [sources, settings] = await Promise.all([api('/sources'), api('/salidzini/settings')]);
  state.sources = sources; state.salidziniMode = settings.mode; renderSources();
  state.resultRenderSignature = '';
  if (state.currentRunId) await pollRun(state.currentRunId);
  else renderResults();
}

async function loadBrowserBridge() {
  const root = byId('browser-bridge-state');
  try {
    const bridge = await api('/browser-bridge/status');
    const capturesChanged = state.captureRevision != null && state.captureRevision !== bridge.capture_revision;
    state.captureRevision = bridge.capture_revision;
    if (capturesChanged && state.currentRunId) {
      await pollRun(state.currentRunId);
      await loadMonitoringHistory();
    }
    root.classList.toggle('connected', bridge.connected);
    const current = bridge.jobs?.[0];
    const detail = current ? ` · checking ${current.shop_key} for ${current.model}` : '';
    const autoNotice = state.salidziniMode !== 'manual' && bridge.connected && !bridge.automatic_salidzini ? ' · Reload the v5.0.8+ extension for Salidzini Auto' : '';
    const transport = bridge.transport === 'websocket' ? ' · live channel' : bridge.transport === 'polling' ? ' · recovery polling' : '';
    const clients = (bridge.clients || []).filter(client => client.connected);
    const switches = clients.length > 1 ? `<span class="browser-switches">${clients.map(client => `<button type="button" class="compact ${client.active ? '' : 'secondary'}" data-switch-client="${escapeHtml(client.id)}" ${client.active ? 'disabled' : ''}>${escapeHtml(client.browser_name)}${client.active ? ' · active' : ' · use'}</button>`).join('')}</span>` : '';
    root.innerHTML = `<span class="bridge-dot"></span><span>${bridge.connected ? `${escapeHtml(bridge.active_browser || 'Browser')} extension connected${transport}${detail}${autoNotice}` : 'Extension not connected · Salidzini Auto needs the extension; manual entry remains available'}</span>${switches}`;
  } catch {
    root.classList.remove('connected');
    root.innerHTML = '<span class="bridge-dot"></span><span>Browser extension status unavailable</span>';
  }
}
async function updateSource(key, enabled) {
  try { await api(`/sources/${encodeURIComponent(key)}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled }) }); await loadSources(); }
  catch (error) { showBanner('error', error.message); await loadSources(); }
}
async function updateSourceMethod(key, collectionMethod) {
  try {
    await api(`/sources/${encodeURIComponent(key)}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ collection_method: collectionMethod }) });
    await loadSources(); showBanner('success', 'Collection method updated.');
  } catch (error) { showBanner('error', error.message); await loadSources(); }
}

function openMethodTest(shopKey) {
  const shop = state.sources.find(item => item.key === shopKey);
  const models = state.sourceOptions.filter(item => item.state !== 'trash' && !item.paused);
  byId('method-test-shop').value = shopKey;
  byId('method-test-title').textContent = `Test ${shop?.name || shopKey}`;
  byId('method-test-item').innerHTML = models.map(item => `<option value="${item.id}">${escapeHtml(item.model)}</option>`).join('');
  byId('method-test-method').innerHTML = SHOP_METHODS.map(([value, label]) => `<option value="${value}" ${value === (shop?.collection_method || 'auto') ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('');
  byId('method-test-result').className = 'method-test-result muted';
  byId('method-test-result').textContent = models.length ? 'Ready to run one isolated request path.' : 'Add an active monitoring model first.';
  byId('method-test-run').disabled = !models.length;
  byId('method-test-dialog').showModal();
}

async function runMethodTest() {
  const button = byId('method-test-run');
  const shopKey = byId('method-test-shop').value;
  button.disabled = true; button.textContent = 'Testing…';
  byId('method-test-result').className = 'method-test-result muted';
  byId('method-test-result').textContent = 'Opening one collection path. This can take up to the configured browser timeout.';
  try {
    const result = await api(`/sources/${encodeURIComponent(shopKey)}/test`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ item_id: Number(byId('method-test-item').value), method: byId('method-test-method').value })
    });
    const attempts = (result.attempts || []).map(attempt => `<li><strong>${escapeHtml(attempt.method)}</strong> · ${escapeHtml(attempt.result)} · ${escapeHtml(attempt.duration_ms)} ms${attempt.error ? `<br><span>${escapeHtml(attempt.error)}</span>` : ''}</li>`).join('');
    const price = result.price_eur == null ? '—' : `${Number(result.price_eur).toFixed(2)} EUR`;
    byId('method-test-result').className = `method-test-result ${statusClass(result.status)}`;
    byId('method-test-result').innerHTML = `<div><strong>${escapeHtml(result.status)}</strong> · ${escapeHtml(result.model)} · ${price} · total ${escapeHtml(result.duration_ms)} ms</div>${result.error ? `<p>${escapeHtml(result.error)}</p>` : ''}${attempts ? `<ol>${attempts}</ol>` : ''}`;
  } catch (error) {
    byId('method-test-result').className = 'method-test-result failed';
    byId('method-test-result').textContent = error.message;
  } finally { button.disabled = false; button.textContent = 'Run one test'; }
}
async function updateMaster(kind, enabled) {
  try { await api(`/sources/master/${kind}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled }) }); await loadSources(); }
  catch (error) { showBanner('error', error.message); await loadSources(); }
}

function findItem(id) { return [...state.source, ...state.stock].find(item => item.id === Number(id)); }
function openEditor(kind, item = null) {
  byId('item-form').reset(); byId('item-kind').value = kind; byId('item-id').value = item?.id || '';
  byId('dialog-kind').textContent = kind.toUpperCase(); byId('dialog-title').textContent = item ? 'Edit item' : 'New item';
  byId('source-fields').hidden = kind !== 'source'; byId('stock-fields').hidden = kind !== 'stock'; byId('item-paused').checked = Boolean(item?.paused);
  if (kind === 'source') {
    byId('source-model').value = item?.model || ''; const sheets = item?.source_sheets || ['TV'];
    document.querySelectorAll('[name="source-sheet"]').forEach(input => { input.checked = sheets.includes(input.value); });
    document.querySelectorAll('[data-shop-link]').forEach(input => { input.value = item?.shop_links?.[input.dataset.shopLink] || ''; });
    document.querySelectorAll('[data-marketplace-link]').forEach(input => { input.value = item?.marketplace_links?.[input.dataset.marketplaceLink] || ''; });
  } else {
    byId('stock-name').value = item?.nomenclature || ''; byId('stock-model').value = item?.model || ''; byId('stock-warehouse').value = item?.warehouse || '';
    byId('stock-quantity').value = item?.quantity ?? 0; byId('stock-cost').value = item?.unit_cost_eur ?? 0;
  }
  byId('item-dialog').showModal();
}

async function saveItem(event) {
  event.preventDefault(); const kind = byId('item-kind').value; const id = byId('item-id').value;
  const shopLinks = Object.fromEntries([...document.querySelectorAll('[data-shop-link]')].map(input => [input.dataset.shopLink, input.value.trim()]));
  const marketplaceLinks = Object.fromEntries([...document.querySelectorAll('[data-marketplace-link]')].map(input => [input.dataset.marketplaceLink, input.value.trim()]));
  const payload = kind === 'source' ? { model: byId('source-model').value, source_sheets: [...document.querySelectorAll('[name="source-sheet"]:checked')].map(input => input.value), shop_links: shopLinks, marketplace_links: marketplaceLinks, paused: byId('item-paused').checked }
    : { nomenclature: byId('stock-name').value, model: byId('stock-model').value, warehouse: byId('stock-warehouse').value, quantity: Number(byId('stock-quantity').value || 0), unit_cost_eur: Number(byId('stock-cost').value || 0), paused: byId('item-paused').checked };
  try {
    await api(id ? `/catalog/items/${id}` : `/catalog/items/${kind}`, { method: id ? 'PATCH' : 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    byId('item-dialog').close(); await loadCatalog(); await loadSetupStatus(); showBanner('success', id ? 'Item updated.' : 'Item added.');
  } catch (error) { showBanner('error', error.message); }
}

async function handleItemAction(event) {
  const button = event.target.closest('[data-action]'); if (!button) return; const item = findItem(button.dataset.id); if (!item) return;
  try {
    if (button.dataset.action === 'edit') return openEditor(item.kind, item);
    if (button.dataset.action === 'pause') await api(`/catalog/items/${item.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ paused: !item.paused }) });
    if (button.dataset.action === 'trash') await api(`/catalog/items/${item.id}`, { method: 'DELETE' });
    if (button.dataset.action === 'restore') await api(`/catalog/items/${item.id}/restore`, { method: 'POST' });
    if (button.dataset.action === 'delete-permanently') {
      if (!window.confirm(uiText('Delete this position permanently? This cannot be undone.'))) return;
      await api(`/catalog/items/${item.id}/permanent`, { method: 'DELETE' });
      showBanner('success', 'Position deleted permanently.');
    }
    if (button.dataset.action === 'monitor') {
      const monitored = await api(`/catalog/items/${item.id}/monitor`, { method: 'POST' });
      showBanner('success', `${monitored.model} is active in monitoring.`);
    }
    await loadCatalog(); await loadSetupStatus();
  } catch (error) { showBanner('error', error.message); }
}

async function upload(kind) {
  const input = byId(kind === 'workbook' ? 'workbook-file' : 'stock-file'); const button = byId(kind === 'workbook' ? 'workbook-upload' : 'stock-upload');
  if (!input.files[0]) return showBanner('error', 'Choose an Excel file first.');
  const form = new FormData(); form.append('file', input.files[0]); button.disabled = true;
  try {
    const result = await api(kind === 'workbook' ? '/workbook/upload' : '/stock/upload', { method: 'POST', body: form }); input.value = '';
    await Promise.all([loadCatalog(), loadSetupStatus()]); showBanner('success', `Imported ${result.models_found ?? result.imported} positions.${result.enrolled != null ? ` ${result.enrolled} new monitoring models. ${result.needs_review || 0} stock rows need model review.` : ''}`);
  } catch (error) { showBanner('error', error.message); } finally { button.disabled = false; }
}

async function loadSetupStatus() {
  const [workbook, stock] = await Promise.all([api('/workbook'), api('/stock')]);
  byId('workbook-status').textContent = `${workbook.models_found} models · ${workbook.source_workbook}`;
  byId('stock-status').textContent = `${stock.count} items · ${stock.matched} linked to models`;
}

function euro(value) { return value == null ? '—' : `${Number(value).toFixed(2)} EUR`; }
function manualDecisionText(decision) {
  if (!decision) return '';
  const when = decision.decided_at ? new Date(decision.decided_at).toLocaleString(uiLocale()) : uiText('time unavailable');
  if (decision.status === 'NOT_FOUND') return `Not found · decided ${when}`;
  const seller = decision.seller_name ? ` · ${decision.seller_name}` : '';
  return `${euro(decision.price_eur)} · ${(decision.availability || 'IN_STOCK').replaceAll('_', ' ')}${seller} · decided ${when}`;
}
function previousDecisionHtml(decision) {
  return decision ? `<span class="previous-decision"><b>Previous manual decision:</b> ${escapeHtml(manualDecisionText(decision))}</span>` : '';
}
function offerLink(offer, warning = '') {
  if (!offer) return '—'; const label = `${euro(offer.price_eur)}${offer.store ? ` · ${escapeHtml(offer.store)}` : ''}${offer.price_basis === 'loyalty' ? ' · Loyalty price' : ''}${offer.matched_model ? ` · matched ${escapeHtml(offer.matched_model)}` : ''}`;
  const attrs = warning ? ` class="price-anomaly" title="${escapeHtml(warning)}"` : '';
  return offer.url ? `<a${attrs} href="${escapeHtml(offer.url)}" target="_blank" rel="noopener">${label}${warning ? ' ⚠' : ''}</a>` : `<span${attrs}>${label}${warning ? ' ⚠' : ''}</span>`;
}

function sourceToken(value) { return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }
function marketplaceSourceForTask(task) {
  const explicitKey = String(task.marketplace_key || '').toLowerCase();
  const taskToken = sourceToken(task.marketplace);
  return state.sources.find(source => source.kind === 'marketplace' && (
    source.key === explicitKey || taskToken.includes(sourceToken(source.key)) || taskToken.includes(sourceToken(source.name))
  ));
}
function marketplaceTaskVisible(task) {
  const source = marketplaceSourceForTask(task);
  return !source || source.effective_enabled;
}
function shopResultVisible(result) {
  const source = state.sources.find(item => item.kind === 'shop' && item.key === result.shop_key);
  return !source || source.effective_enabled;
}
function visibleRunResults() {
  return state.tasks.filter(marketplaceTaskVisible);
}

function aggregateResults() {
  const rows = new Map();
  const ensure = (model, canonical = '') => {
    const key = String(canonical || model || '').trim().toUpperCase();
    if (!rows.has(key)) rows.set(key, { key, model: model || canonical, itemId: null, tasks: [], shops: {}, stockQuantity: null, stockCost: null });
    return rows.get(key);
  };
  state.tasks.forEach(task => {
    const row = ensure(task.source_model || task.canonical_model, task.canonical_model);
    if (marketplaceTaskVisible(task)) row.tasks.push(task);
    if (task.item_id != null) row.itemId = Number(task.item_id);
    if (task.stock_quantity != null) row.stockQuantity = task.stock_quantity; if (task.stock_unit_cost_eur != null) row.stockCost = task.stock_unit_cost_eur;
  });
  state.shopResults.filter(shopResultVisible).forEach(result => {
    const row = ensure(result.model, result.model);
    const enabled = new Set(row.tasks.map(t => t.marketplace_key));
    const observations = (result.observations || []).filter(o => enabled.has(o.marketplace_key));
    const inStock = observations.filter(o => o.availability === 'IN_STOCK');
    const best = [...(inStock.length ? inStock : observations)].sort((a,b) => a.price_eur-b.price_eur)[0];
    const complete = row.tasks.length && row.tasks.every(t => ['SUCCESS','NOT_FOUND'].includes(t.status) && ['complete','reported_gap'].includes(t.coverage));
    row.shops[result.shop_key] = {...result, observations, price_eur:best?.price_eur, availability:best?.availability, price_basis:best?.price_basis,
      status:best ? 'SUCCESS' : complete ? 'NOT_LISTED' : 'UNVERIFIED', coverage:complete ? 'complete' : 'partial'};
    row.itemId = Number(result.item_id);
  });
  // Historical rows come from the run snapshot, never today's catalog.
  return [...rows.values()].sort((a, b) => a.model.localeCompare(b.model, undefined, { numeric: true }));
}

function rowStatus(row) {
  const statuses = row.tasks.map(item => item.status);
  if (statuses.some(value => ['RUNNING', 'PENDING'].includes(value))) return 'RUNNING';
  if (statuses.some(value => value === 'ACTION_REQUIRED')) return 'ACTION_REQUIRED';
  if (statuses.some(value => value === 'COOLDOWN')) return 'COOLDOWN';
  if (statuses.some(value => value === 'SUCCESS')) return 'SUCCESS';
  if (statuses.some(value => value === 'FAILED')) return 'FAILED';
  if (statuses.some(value => value === 'INCOMPLETE')) return 'INCOMPLETE';
  return statuses.length ? 'NOT_FOUND' : 'NOT_STARTED';
}

function resultCounts(row) {
  const statuses = row.tasks.map(item => item.status);
  return {
    success: statuses.filter(value => value === 'SUCCESS').length,
    failed: statuses.filter(value => ['FAILED', 'INCOMPLETE'].includes(value)).length,
    notFound: statuses.filter(value => value === 'NOT_FOUND').length,
    actionRequired: statuses.filter(value => value === 'ACTION_REQUIRED').length,
    cooldown: statuses.filter(value => value === 'COOLDOWN').length,
    cached: row.tasks.filter(item => item.cached).length,
    pending: statuses.filter(value => ['RUNNING', 'PENDING'].includes(value)).length
  };
}

function statusCell(row) {
  const counts = resultCounts(row); const parts = [];
  parts.push(badge(`Success ${counts.success}`, 'success'));
  parts.push(badge(`Failed ${counts.failed}`, counts.failed ? 'failed' : 'not-found', STATUS_HELP.failed));
  parts.push(badge(`Not found ${counts.notFound}`, 'not-found'));
  if (counts.actionRequired) parts.push(badge(`Action required ${counts.actionRequired}`, 'action-required'));
  if (counts.cooldown) parts.push(badge(`Cooldown ${counts.cooldown}`, 'cooldown'));
  if (counts.cached) parts.push(badge(`Cached ${counts.cached}`, 'cached'));
  if (counts.pending) parts.push(badge(`Pending ${counts.pending}`, 'incomplete'));
  return `<span class="status-counts">${parts.join(' ')}</span>`;
}

function lowestOffer(row, field) {
  const offers = row.tasks.map(task => task[field]).filter(Boolean);
  return offers.sort((a, b) => Number(a.price_eur) - Number(b.price_eur))[0] || null;
}

function rowPriceValues(row) {
  const values = [];
  row.tasks.filter(task => task.status === 'SUCCESS').forEach(task => {
    for (const offer of [task.cheapest_in_stock, task.cheapest_pre_order, task.lowest_reported, task.highest_reported]) {
      if (offer?.price_eur != null) values.push(Number(offer.price_eur));
    }
  });
  Object.values(row.shops).filter(item => item.status === 'SUCCESS' && item.price_eur != null)
    .forEach(item => values.push(Number(item.price_eur)));
  return [...new Set(values.filter(Number.isFinite).map(value => Number(value.toFixed(2))))].sort((a, b) => a - b);
}

function priceAnomalyWarning(row, value) {
  const price = Number(value); const prices = rowPriceValues(row);
  if (!Number.isFinite(price) || prices.length < 2 || prices[0] <= 0) return '';
  const minimum = prices[0]; const next = prices.find(candidate => candidate > minimum);
  if (price > minimum && (price - minimum) / minimum >= .5) {
    return `Price warning: ${Math.round((price - minimum) / minimum * 100)}% above the lowest collected price (${euro(minimum)}). Verify the exact model.`;
  }
  if (Math.abs(price - minimum) < .01 && next && (next - minimum) / next >= .5) {
    return `Price warning: ${Math.round((next - minimum) / next * 100)}% below the next collected price (${euro(next)}). Verify the exact model.`;
  }
  return '';
}

function correctionButton(kind, itemId, sourceKey) {
  if (itemId == null || !sourceKey) return '';
  return `<button type="button" class="compact secondary correct-result-button" data-correct-kind="${escapeHtml(kind)}" data-correct-item="${itemId}" data-correct-source="${escapeHtml(sourceKey)}">Add seller offer / review</button>`;
}

function marketplaceCell(row, openDetails, maximum = false) {
  if (!row.tasks.length) return '—';
  const detailKey = `${row.key}:marketplaces:${maximum ? 'max' : 'min'}`;
  const summaries = row.tasks.map(task => {
    const offer = task[maximum ? 'highest_reported' : 'lowest_reported'];
    const availabilityNote = offer ? ` · ${offer.availability === 'UNKNOWN' ? 'availability unconfirmed' : offer.availability.toLowerCase().replaceAll('_', ' ')}` : '';
    const coverageNote = task.coverage === 'reported_gap' ? ' · all visible offers collected; marketplace count differs' : task.coverage !== 'complete' ? ' · partial' : '';
    const note = availabilityNote + coverageNote;
    return `<span class="marketplace-summary-offer"><b>${escapeHtml(task.marketplace)}:</b> ${offer ? offerLink(offer, priceAnomalyWarning(row, offer.price_eur)) : badge(task.status.replaceAll('_', ' '), statusClass(task.status))}<small>${escapeHtml(note)}</small></span>`;
  }).join('');
  const details = row.tasks.map(task => {
    const source = marketplaceSourceForTask(task);
    const offers = (task.offers || []).map((offer, index) => `<div class="v5-offer">${offerLink(offer, priceAnomalyWarning(row, offer.price_eur))}<span>${escapeHtml(offer.availability === 'UNKNOWN' ? 'Availability unknown' : offer.availability.replaceAll('_', ' '))}</span><span class="offer-controls"><button type="button" class="link-action" data-correct-kind="marketplaces" data-correct-item="${task.item_id}" data-correct-source="${escapeHtml(task.marketplace_key)}" data-offer-index="${index}">Edit offer</button><button type="button" class="link-action danger" data-remove-offer="${index}" data-item="${task.item_id}" data-key="${escapeHtml(task.marketplace_key)}">Remove false match</button></span></div>`).join('');
    const coverage = task.coverage === 'complete' ? 'Page coverage complete' : task.coverage === 'accepted_partial' ? 'Collected offers accepted in Quick Review' : task.coverage === 'reported_gap' ? `All visible offers collected — ${escapeHtml(task.coverage_detail || 'marketplace heading count differs')}; this result is refreshed next run` : 'Partial coverage — min/max reflect captured exact offers only';
    const undo = task.undo_snapshot ? `<button type="button" class="compact secondary" data-undo-review data-item="${task.item_id}" data-key="${escapeHtml(task.marketplace_key)}">Undo last decision</button>` : '';
    return `<div class="detail-offer"><strong>${escapeHtml(task.marketplace)} · ${task.offers?.length || 0} captured offers</strong><span>${coverage}</span>${offers || '<span>No reliable offers yet.</span>'}<span class="muted">${task.finished_at ? 'Checked ' + escapeHtml(new Date(task.finished_at).toLocaleString(uiLocale())) : 'Queued'}${task.cached ? ' · cached' : ''}</span>${previousDecisionHtml(task.previous_manual_resolution)}${task.error ? `<span class="detail-error">${escapeHtml(task.error)}</span>` : ''}${correctionButton('marketplaces', task.item_id, source?.key || task.marketplace_key)}${undo}</div>`;
  }).join('');
  return `<details class="cell-details marketplace-details" data-detail-key="${escapeHtml(detailKey)}" ${openDetails.has(detailKey) ? 'open' : ''}><summary>${summaries}</summary>${details}</details>`;
}

function shopCell(row, shop, openDetails) {
  const item = row.shops[shop.key];
  if (!item) return '—';
  const detailKey = `${row.key}:shop:${shop.key}`;
  const label = item.price_eur != null ? euro(item.price_eur) + (item.price_basis === 'loyalty' ? ' · Loyalty price' : '') : item.status.replaceAll('_', ' ');
  const observations = (item.observations || []).map(offer => `<div class="v5-offer"><b>${escapeHtml(offer.marketplace)}</b>${offerLink(offer, priceAnomalyWarning(row, offer.price_eur))}<span>${escapeHtml(offer.availability === 'UNKNOWN' ? 'Availability unknown' : offer.availability.replaceAll('_', ' '))}</span><span class="muted">${escapeHtml(new Date(offer.checked_at).toLocaleString(uiLocale()))}${offer.cached ? ' · cached' : ''}</span></div>`).join('');
  const warning = priceAnomalyWarning(row, item.price_eur);
  return `<details class="cell-details" data-detail-key="${escapeHtml(detailKey)}" ${openDetails.has(detailKey) ? 'open' : ''}><summary><span class="${warning ? 'price-anomaly' : ''}" title="${escapeHtml(warning)}">${badge(label, statusClass(item.status))}</span></summary><div class="detail-offer"><span>Marketplace observations only. The retailer was not queried.</span>${item.coverage !== 'complete' ? '<span class="muted">Coverage incomplete — more offers may exist.</span>' : ''}${observations || '<span>No captured offers from this seller.</span>'}</div></details>`;
}

function columns() {
  const marketplacesEnabled = state.sources.some(item => item.kind === 'marketplace' && item.effective_enabled);
  const shops = state.sources.filter(item => item.kind === 'shop' && item.effective_enabled);
  return [
    { key: 'model', label: 'Model' }, ...(marketplacesEnabled ? [{ key: 'marketplaces', label: 'Marketplace min price' }, { key: 'marketplaces-max', label: 'Marketplace max price' }] : []), { key: 'lowest-stock', label: 'Lowest in-stock' }, { key: 'lowest-preorder', label: 'Lowest pre-order' },
    ...shops.map(shop => ({ key: `shop-${shop.key}`, label: shop.name, shop })), { key: 'stock', label: 'Stock' }, { key: 'margin', label: 'Margin' }, { key: 'status', label: 'Status' }
  ];
}

function setColumnHidden(key, hidden) {
  if (hidden) state.hiddenColumns.add(key); else state.hiddenColumns.delete(key);
  localStorage.setItem(HIDDEN_COLUMNS_KEY, JSON.stringify([...state.hiddenColumns])); renderResults();
}

function buildResultFilters(rows) {
  const values = {
    model: rows.map(row => ({ value: row.key, label: row.model })),
    status: [...new Set(rows.map(rowStatus))].map(value => ({ value, label: value.replaceAll('_', ' ') })),
    marketplace: state.sources.filter(item => item.kind === 'marketplace' && item.effective_enabled).map(item => ({ value: item.key, label: item.name })),
    shop: state.sources.filter(item => item.kind === 'shop' && item.effective_enabled).map(item => ({ value: item.key, label: item.name }))
  };
  for (const [kind, options] of Object.entries(values)) {
    const known = state.resultFilterKnown[kind];
    if (!state.resultFilterInitialized) options.forEach(option => state.resultFilters[kind].add(option.value));
    else {
      const allowed = new Set(options.map(option => option.value));
      [...state.resultFilters[kind]].filter(value => !allowed.has(value)).forEach(value => state.resultFilters[kind].delete(value));
      options.filter(option => !known.has(option.value)).forEach(option => state.resultFilters[kind].add(option.value));
    }
    state.resultFilterKnown[kind] = new Set(options.map(option => option.value));
    renderMultiFilter(`${kind}-filter`, options, state.resultFilters[kind], renderResults, 'No options', kind === 'model');
  }
  state.resultFilterInitialized = true;
}

function resultRowVisible(row) {
  if (!state.resultFilters.model.has(row.key) || !state.resultFilters.status.has(rowStatus(row))) return false;
  const marketplaceKeys = row.tasks.map(task => marketplaceSourceForTask(task)?.key || String(task.marketplace || '').toLowerCase());
  if (marketplaceKeys.length && !marketplaceKeys.some(key => state.resultFilters.marketplace.has(key))) return false;
  const shopKeys = Object.keys(row.shops);
  if (shopKeys.length && !shopKeys.some(key => state.resultFilters.shop.has(key))) return false;
  return true;
}

function renderResults() {
  const openDetails = new Set(
    [...document.querySelectorAll('#result-rows details[data-detail-key][open]')]
      .map(detail => detail.dataset.detailKey)
  );
  const rows = aggregateResults(); buildResultFilters(rows); const cols = columns();
  byId('result-head').innerHTML = cols.map(col => `<th data-col="${escapeHtml(col.key)}" class="${state.hiddenColumns.has(col.key) ? 'col-hidden' : ''}">${escapeHtml(col.label)}</th>`).join('');
  renderMultiFilter('column-filter', cols.map(col => ({ value: col.key, label: col.label })), new Set(cols.filter(col => !state.hiddenColumns.has(col.key)).map(col => col.key)), () => {});
  byId('column-filter').querySelectorAll('input').forEach(input => input.addEventListener('change', () => setColumnHidden(input.value, !input.checked)));
  const cell = (key, content, extra = '') => `<td data-col="${key}" class="${extra} ${state.hiddenColumns.has(key) ? 'col-hidden' : ''}">${content}</td>`;
  byId('result-rows').innerHTML = rows.length ? rows.map(row => {
    const stockOffer = lowestOffer(row, 'cheapest_in_stock'); const preorderOffer = lowestOffer(row, 'cheapest_pre_order');
    const best = stockOffer || preorderOffer; const margin = best && row.stockCost != null ? Number(best.price_eur) - Number(row.stockCost) : null;
    const marketplacesEnabled = state.sources.some(item => item.kind === 'marketplace' && item.effective_enabled);
    const shopCells = state.sources.filter(item => item.kind === 'shop' && item.effective_enabled).map(shop => cell(`shop-${shop.key}`, shopCell(row, shop, openDetails), 'shop-cell')).join('');
    const marketplaceResultCell = marketplacesEnabled ? cell('marketplaces', marketplaceCell(row, openDetails), 'source-cell') + cell('marketplaces-max', marketplaceCell(row, openDetails, true), 'source-cell') : '';
    const refresh = row.itemId ? `<button type="button" class="refresh-model-button" data-refresh-model="${row.itemId}" title="Refresh this model on enabled marketplaces only" aria-label="Refresh ${escapeHtml(row.model)}">↻</button>${copyModelButton(row.model)}` : '';
    return `<tr class="${resultRowVisible(row) ? '' : 'result-row-filtered'}">${cell('model', `<span class="result-model"><span>${escapeHtml(row.model)}</span>${refresh}</span>`, 'model-cell')}${marketplaceResultCell}${cell('lowest-stock', offerLink(stockOffer, priceAnomalyWarning(row, stockOffer?.price_eur)))}${cell('lowest-preorder', offerLink(preorderOffer, priceAnomalyWarning(row, preorderOffer?.price_eur)))}${shopCells}${cell('stock', row.stockQuantity == null ? '—' : `${escapeHtml(row.stockQuantity)} / ${euro(row.stockCost)}`)}${cell('margin', margin == null ? '—' : `${margin >= 0 ? '+' : ''}${margin.toFixed(2)} EUR`)}${cell('status', statusCell(row))}</tr>`;
  }).join('') : `<tr><td colspan="${cols.length}" class="empty">No monitoring results yet.</td></tr>`;
}

function renderActionRequired(run) {
  const shopItems = [];
  const marketplaceItems = state.tasks.filter(item => item.status === 'ACTION_REQUIRED' && item.assisted && marketplaceTaskVisible(item)).map(item => ({ ...item, model: item.source_model || item.canonical_model, action_kind: 'marketplaces', action_key: item.marketplace_key, action_name: item.marketplace || item.marketplace_key }));
  const items = [...shopItems, ...marketplaceItems];
  state.actionItems = items;
  const review = byId('review-actions');
  review.hidden = items.length === 0;
  review.textContent = items.length ? `Review required checks (${items.length})` : 'Review required checks';
  const renderSignature = JSON.stringify(items.map(item => ({
    identity: `${item.action_kind}:${item.item_id}:${item.action_key}`,
    model: item.model,
    name: item.action_name,
    error: item.error || '',
    product_url: item.product_url || '',
    search_url: item.search_url || '',
    status: item.status,
    retry_after: item.retry_after || '',
    previous: item.previous_manual_resolution || null,
    candidates: item.candidate_matches || [],
  })));
  const editing = byId('action-items').querySelector('.action-popover:not([hidden]):not(.saved)');
  if (renderSignature !== state.actionRenderSignature && !editing) {
    state.actionRenderSignature = renderSignature;
    byId('action-items').innerHTML = items.length ? items.map(item => {
    const link = item.product_url || item.search_url;
    const identity = `${item.action_kind}:${item.item_id}:${item.action_key}`;
    const previous = item.previous_manual_resolution || {};
    const previousPrice = previous.status === 'SUCCESS' && previous.price_eur != null ? previous.price_eur : '';
    const sellerField = `<label>Seller / shop<input data-action-field="seller" autocomplete="off" value="${escapeHtml(previous.seller_name || '')}" placeholder="Seller shown on the marketplace" required></label><label>Availability<select data-action-field="availability"><option value="UNKNOWN">Availability unknown</option><option value="IN_STOCK">In stock</option><option value="PRE_ORDER">Pre-order</option><option value="OUT_OF_STOCK">Out of stock</option></select></label>`;
    const attrs = `data-check-kind="${item.action_kind}" data-item-id="${item.item_id}" data-source-key="${escapeHtml(item.action_key)}"`;
    const cooldown = false;
    const retryAt = item.retry_after ? new Date(item.retry_after).toLocaleString(uiLocale()) : '';
    const retryAction = item.action_key === 'salidzini'
      ? `${state.salidziniMode !== 'manual' ? `<button type="button" data-check-action="retry" ${attrs}>Retry automatic check</button>` : ''}<span class="muted">Open &amp; collect waits for CAPTCHA and saves verified results automatically. To select offers yourself: Open only → Send to PriceMonitor → review and save. Each marketplace is a separate check.</span>`
      : cooldown
      ? `<button type="button" data-check-action="wait" ${attrs}>Wait & retry automatically</button>`
      : `<button type="button" data-check-action="retry" ${attrs}>Capture again</button>`;
    const cooldownChoice = cooldown ? `<span class="action-cooldown-choice">Paused until ${escapeHtml(retryAt)}. Choose automatic waiting or enter a manual result now.</span>` : '';
    const candidates = item.candidate_matches?.length ? `<div class="candidate-matches quick-review"><strong>Quick Review · choose the matching product</strong>${item.candidate_matches.slice(0,2).map((c,index) => `<div class="candidate-card"><span class="candidate-number">${index + 1}</span><div><b>${escapeHtml(c.model || c.title)}</b><a href="${escapeHtml(c.url)}" target="_blank" rel="noopener">${escapeHtml(c.title)}</a></div><button type="button" data-check-action="accept-candidate" data-candidate-index="${index}" ${attrs}>Use ${index + 1}</button></div>`).join('')}<label class="remember-alias"><input type="checkbox" data-action-field="remember-alias"> Remember this SKU alias for future runs</label><span class="muted">Keyboard: 1/2 selects a candidate, 0 marks Not found. No price is accepted until you choose.</span></div>` : '';
    const acceptPartial = item.offers?.length && item.coverage === 'partial' ? `<button type="button" class="secondary" data-check-action="accept-partial" ${attrs}>Accept ${item.offers.length} collected offer${item.offers.length === 1 ? '' : 's'}</button>` : '';
    return `<div class="action-item" data-action-item="${escapeHtml(identity)}"><div class="action-item-heading"><div><span class="action-model"><strong>${escapeHtml(item.model)}</strong>${copyModelButton(item.model)}<span>· ${escapeHtml(item.action_name)}</span></span><span class="muted">${escapeHtml(item.error || 'Browser verification is required before this price can be collected.')}</span>${cooldownChoice}${previousDecisionHtml(item.previous_manual_resolution)}${candidates}</div></div><div class="action-item-actions">${acceptPartial}<button type="button" data-check-action="collect" ${attrs} title="Open the marketplace, complete CAPTCHA if needed, then collect automatically. Closes only after the full result is saved. Requires extension v5.0.9+.">Open &amp; collect</button>${link ? `<a class="button-link secondary" href="${escapeHtml(link)}" target="_blank" rel="noopener" title="Open without automatic capture or closing">Open only</a>` : ''}${retryAction}
      <span class="action-control"><button type="button" class="secondary" data-check-action="toggle-not-found" ${attrs}>Mark not found</button><span class="action-popover" data-action-popover="not-found" hidden><strong>Confirm not found?</strong><span>This saves a final Not found result for this source.</span><span class="popover-actions"><button type="button" class="secondary compact" data-check-action="cancel-popover">Cancel</button><button type="button" class="compact danger-fill" data-check-action="confirm-not-found" ${attrs}>Confirm</button></span></span></span>
      <span class="action-control"><button type="button" class="secondary" data-check-action="toggle-price" ${attrs}>Save manual price</button><span class="action-popover action-form-popover" data-action-popover="price" hidden><label>Price, EUR<input data-action-field="price" inputmode="decimal" value="${escapeHtml(previousPrice)}" placeholder="0.00"></label>${sellerField}<span class="popover-actions"><button type="button" class="secondary compact" data-check-action="cancel-popover">Cancel</button><button type="button" class="compact" data-check-action="confirm-price" ${attrs}>Save price</button></span></span></span>
      <span class="action-control"><button type="button" class="secondary" data-check-action="toggle-link" ${attrs}>Add product link</button><span class="action-popover action-form-popover link-popover" data-action-popover="link" hidden><label>Product or search URL<input data-action-field="url" type="url" value="${escapeHtml(item.product_url || '')}" placeholder="https://…"></label><span class="muted">The link is saved to this SKU and parsed now. Future checks try it first.</span><span class="popover-actions"><button type="button" class="secondary compact" data-check-action="cancel-popover">Cancel</button><button type="button" class="compact" data-check-action="confirm-link" ${attrs}>Save and parse</button></span></span></span></div></div>`;
    }).join('') : '<p class="muted">No checks currently require browser verification.</p>';
  }

  if (!items.length) {
    state.lastActionSignature = '';
    if (byId('action-dialog').open && !editing) byId('action-dialog').close();
    return;
  }
  // Review is intentionally user-opened. Reopening the application, language
  // changes and history navigation must never interrupt the user with a modal.
  state.lastActionSignature = items.map(item => `${item.action_kind}:${item.item_id}:${item.action_key}`).sort().join('|');
}

async function handleActionDialog(event) {
  const copyButton = event.target.closest('[data-copy-model]');
  if (copyButton) return copyModel(copyButton);
  const button = event.target.closest('[data-check-action]');
  if (!button || !state.currentRunId) return;
  const action = button.dataset.checkAction;
  const actionItem = button.closest('.action-item');
  if (action === 'cancel-popover') {
    button.closest('.action-popover').hidden = true;
    return;
  }
  if (action.startsWith('toggle-')) {
    const target = action.replace('toggle-', '');
    actionItem.querySelectorAll('[data-action-popover]').forEach(popover => {
      popover.hidden = popover.dataset.actionPopover !== target || !popover.hidden;
    });
    const opened = actionItem.querySelector(`[data-action-popover="${target}"]:not([hidden]) input`);
    if (opened) opened.focus();
    return;
  }
  let payload = null;
  if (action === 'confirm-not-found') {
    payload = { status: 'NOT_FOUND' };
  }
  if (action === 'confirm-price') {
    const entered = actionItem.querySelector('[data-action-field="price"]').value;
    const price = Number(entered.trim().replace(',', '.'));
    if (!entered.trim() || !Number.isFinite(price) || price <= 0) {
      const field = actionItem.querySelector('[data-action-field="price"]'); field.setCustomValidity(uiText('Enter a valid non-negative price.')); field.reportValidity(); field.setCustomValidity('');
      return;
    }
    payload = { status: 'SUCCESS', price_eur: price, availability: actionItem.querySelector('[data-action-field="availability"]').value };
    const seller = actionItem.querySelector('[data-action-field="seller"]');
    if (seller) {
      if (!seller.value.trim()) { seller.setCustomValidity(uiText('Enter the seller shown on the marketplace.')); seller.reportValidity(); seller.setCustomValidity(''); return; }
      payload.seller_name = seller.value.trim();
    }
  }
  if (action === 'confirm-link') {
    const urlField = actionItem.querySelector('[data-action-field="url"]');
    if (!urlField.value.trim() || !urlField.checkValidity()) { urlField.reportValidity(); return; }
    payload = { url: urlField.value.trim() };
  }
  if (action === 'accept-candidate') {
    payload = { candidate_index: Number(button.dataset.candidateIndex),
      remember_alias: Boolean(actionItem.querySelector('[data-action-field="remember-alias"]')?.checked) };
  }
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = action === 'collect' ? 'Opening…' : action === 'retry' ? 'Capturing…' : action === 'wait' ? 'Scheduling…' : action === 'confirm-link' ? 'Parsing…' : 'Saving…';
  try {
    const base = `/runs/${encodeURIComponent(state.currentRunId)}/${button.dataset.checkKind}/${button.dataset.itemId}/${encodeURIComponent(button.dataset.sourceKey)}`;
    if (action === 'accept-candidate') {
      await api(`${base}/accept-candidate`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    } else if (action === 'accept-partial') {
      await api(`${base}/accept-partial`, { method: 'POST' });
    } else if (action === 'collect') {
      await api(`${base}/open-collect`, { method: 'POST' });
      showBanner('success','Open & collect queued. Complete CAPTCHA if shown; the extension continues automatically and closes its tab only after the full result is saved.');
    } else if (action === 'retry') {
      await api(`${base}/retry`, { method: 'POST' });
    } else if (action === 'wait') {
      await api(`${base}/wait`, { method: 'POST' });
    } else if (action === 'confirm-link') {
      await api(`${base}/link`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    } else {
      await api(`${base}/resolve`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    }
    state.lastActionSignature = '';
    const message = action === 'accept-candidate' ? 'Candidate selected and being collected.' : action === 'accept-partial' ? 'Collected offers accepted.' : action === 'retry' ? 'The selected check is capturing again.' : action === 'wait' ? 'The check will retry automatically when the cooldown ends.' : action === 'confirm-link' ? 'Link saved. PriceMonitor is parsing it now.' : 'Manual result saved.';
    const popover = button.closest('.action-popover'); if (popover) { popover.hidden = false; popover.classList.add('saved'); popover.innerHTML = `<span class="popover-success">${CHECK_ICON} ${escapeHtml(message)}</span>`; }
    await pollRun(state.currentRunId);
    if (action === 'collect' || action === 'retry' || action === 'wait' || action === 'confirm-link' || action === 'accept-candidate') {
      scheduleRunPolling(state.currentRunId, 1000);
    }
  } catch (error) {
    button.disabled = false;
    button.textContent = originalLabel;
    showBanner('error', error.message);
  }
}

function correctionTarget(kind, itemId, sourceKey) {
  if (kind === 'shops') {
    return state.shopResults.find(item => Number(item.item_id) === Number(itemId) && item.shop_key === sourceKey);
  }
  return state.tasks.find(item => Number(item.item_id) === Number(itemId) && (
    (marketplaceSourceForTask(item)?.key || item.marketplace_key) === sourceKey
  ));
}

function openResultCorrection(event) {
  const button = event.target.closest('[data-correct-kind]');
  if (!button) return;
  const kind = button.dataset.correctKind; const itemId = Number(button.dataset.correctItem); const sourceKey = button.dataset.correctSource;
  const item = correctionTarget(kind, itemId, sourceKey);
  if (!item) return showBanner('error', 'The selected result is no longer available.');
  const isMarketplace = kind === 'marketplaces';
  const offerIndex = button.dataset.offerIndex;
  byId('correction-form').dataset.offerIndex = offerIndex ?? '';
  byId('correction-form').dataset.checkedAt = item.finished_at || '';
  const offer = offerIndex != null ? item.offers[Number(offerIndex)] : null;
  const sourceName = isMarketplace ? item.marketplace : item.shop_name || item.shop_key;
  const model = isMarketplace ? item.source_model || item.canonical_model : item.model;
  const previous = item.previous_manual_resolution;
  const currentPrice = isMarketplace ? offer?.price_eur : item.price_eur;
  const currentAvailability = isMarketplace
    ? (item.cheapest_in_stock ? 'IN_STOCK' : item.cheapest_pre_order ? 'PRE_ORDER' : null)
    : item.availability;
  const previousPrice = previous?.status === 'SUCCESS' ? previous.price_eur : null;
  byId('correction-kind').value = kind; byId('correction-item-id').value = itemId; byId('correction-source-key').value = sourceKey;
  byId('correction-title').textContent = `${model} · ${sourceName}`;
  byId('correction-current').innerHTML = `<b>Current result:</b> ${escapeHtml(item.status === 'SUCCESS' ? `${euro(currentPrice)} · ${(currentAvailability || 'IN_STOCK').replaceAll('_', ' ')}` : item.status.replaceAll('_', ' '))}`;
  byId('correction-previous').innerHTML = previous ? `<b>Previous manual decision:</b> ${escapeHtml(manualDecisionText(previous))}` : '<b>Previous manual decision:</b> none';
  byId('correction-price').value = currentPrice ?? previousPrice ?? '';
  byId('correction-availability').value = offer?.availability || previous?.availability || 'UNKNOWN';
  byId('correction-complete').checked = item.coverage === 'complete';
  byId('correction-seller').value = offer?.store || previous?.seller_name || '';
  byId('correction-url').value = (isMarketplace ? offer?.url || item.product_url || item.search_url : item.product_url) || previous?.product_url || '';
  byId('correction-seller-label').hidden = !isMarketplace;
  byId('correction-url-label').hidden = !isMarketplace;
  if (!byId('correction-dialog').open) byId('correction-dialog').showModal();
}

async function saveResultCorrection(status) {
  const kind = byId('correction-kind').value; const itemId = byId('correction-item-id').value; const sourceKey = byId('correction-source-key').value;
  const payload = { status };
  payload.all_offers_reviewed = byId('correction-complete').checked;
  payload.expected_checked_at = byId('correction-form').dataset.checkedAt;
  if (byId('correction-form').dataset.offerIndex !== '') payload.offer_index = Number(byId('correction-form').dataset.offerIndex);
  if (status === 'SUCCESS') {
    const price = Number(byId('correction-price').value.trim().replace(',', '.'));
    if (!byId('correction-price').value.trim() || !Number.isFinite(price) || price <= 0) {
      const field = byId('correction-price'); field.setCustomValidity(uiText('Enter a valid non-negative price.')); field.reportValidity(); field.setCustomValidity(''); return;
    }
    payload.price_eur = price; payload.availability = byId('correction-availability').value;
    if (kind === 'marketplaces') {
      payload.seller_name = byId('correction-seller').value.trim();
      if (!payload.seller_name) { byId('correction-seller').reportValidity(); return; }
      payload.product_url = byId('correction-url').value.trim() || null;
      if (!payload.product_url) { const field = byId('correction-url'); field.setCustomValidity(uiText('Enter the link supporting this corrected price.')); field.reportValidity(); field.setCustomValidity(''); return; }
      if (!byId('correction-url').checkValidity()) { byId('correction-url').reportValidity(); return; }
    }
  }
  const buttons = byId('correction-dialog').querySelectorAll('button'); buttons.forEach(button => { button.disabled = true; });
  try {
    await api(`/runs/${encodeURIComponent(state.currentRunId)}/${kind}/${itemId}/${encodeURIComponent(sourceKey)}/resolve`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload)
    });
    byId('correction-dialog').close(); await pollRun(state.currentRunId);
    showBanner('success', status === 'NOT_FOUND' ? 'Result corrected to Not found.' : 'Corrected price saved.');
  } catch (error) { showBanner('error', error.message); }
  finally { buttons.forEach(button => { button.disabled = false; }); }
}

function renderQueueProgress(execution) {
  const target = byId('queue-progress');
  const batch = execution.queue_progress;
  if (!batch?.marketplaces?.length) { target.innerHTML = ''; return; }
  target.innerHTML = batch.marketplaces.map(row => {
    const task = row.current && row.remaining
      ? `${escapeHtml(row.current.model)} · ${escapeHtml(uiText(row.current.message))}`
      : batch.stopped ? uiText('Stopped') : row.remaining ? uiText('Queued') : uiText('Completed');
    const current = `${task} · ${escapeHtml(uiText(`Finished ${row.finished}/${row.total} · waiting ${row.queued} · checking ${row.running} · review ${row.needs_review}`))}`;
    const eta = row.remaining && row.eta_seconds ? uiText(`ETA ${formatDuration(row.eta_seconds)}`) : `${row.finished}/${row.total}`;
    const health = row.marketplace_key === 'salidzini' ? `<span class="muted">Safe Auto: ${row.safe_pages || 0}/20 pages in this browser cycle${row.cooldown_until ? ` · cooldown until ${escapeHtml(new Date(row.cooldown_until).toLocaleTimeString(uiLocale()))}` : ''}</span>` : '';
    const protection = row.protection_paused ? `<span class="queue-protection">${escapeHtml(uiText(row.protection_reason || 'Protection pause · no more automatic requests in this batch'))}</span>` : '';
    return `<div class="queue-progress-row"><strong>${escapeHtml(row.marketplace)}</strong><span class="queue-progress-current">${current}${health}${protection}</span><span class="queue-progress-eta">${escapeHtml(eta)}</span></div>`;
  }).join('');
}

function renderRun(run) {
  const networkFailures = (run.tasks || []).filter(task => task.status === 'ACTION_REQUIRED' && (task.error_code === 'NETWORK_UNAVAILABLE' || task.error === 'All connection attempts failed'));
  byId('run-network-warning').hidden = !networkFailures.length;
  byId('run-network-warning').textContent = `${networkFailures.length} checks could not connect to the Internet. No page was read for these checks. Check network/firewall/proxy access, restart PriceMonitor from its folder, then retry. This is not a Not found result or a CAPTCHA.`;
  const previousStatus = state.lastRunStatus;
  state.currentRunId = run.id || run.run_id;
  state.tasks = run.tasks || []; state.shopResults = run.shop_results || [];
  state.lastRunStatus = run.status;
  const resultSignature = JSON.stringify([
    state.tasks.map(item => [item.item_id, item.marketplace_key || item.marketplace, item.status, item.offers, item.coverage, item.error, item.cached, item.finished_at]),
    state.shopResults.map(item => [item.item_id, item.shop_key, item.status, item.price_eur, item.availability, item.product_url, item.search_url, item.error, item.retry_after, item.cached, item.checked_at]),
  ]);
  const resultsChanged = resultSignature !== state.resultRenderSignature;
  state.resultRenderSignature = resultSignature;
  if (run.cleared) {
    byId('progress').hidden = true;
    byId('run-state').textContent = 'Table cleared.';
    byId('start-run').disabled = false;
    byId('run-mode').disabled = false;
    byId('clear-run').disabled = true;
    byId('retry-unresolved').disabled = true;
    byId('retry-salidzini').disabled = true;
    byId('test-salidzini').disabled = true;
    byId('export-run').disabled = true;
    byId('stop-run').hidden = true;
    byId('stop-run').disabled = false;
    renderResults(); renderActionRequired(run);
    if (state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; }
    return;
  }
  const all = visibleRunResults(); const finished = all.filter(item => !['RUNNING', 'PENDING'].includes(item.status)).length;
  const success = all.filter(item => item.status === 'SUCCESS').length; const failed = all.filter(item => ['FAILED', 'INCOMPLETE'].includes(item.status)).length;
  const notFound = all.filter(item => item.status === 'NOT_FOUND').length;
  const actionRequired = all.filter(item => item.status === 'ACTION_REQUIRED').length;
  const cooldown = all.filter(item => item.status === 'COOLDOWN').length;
  const cached = all.filter(item => item.cached).length;
  const percent = all.length ? Math.round(finished / all.length * 100) : (run.status === 'COMPLETE' ? 100 : 0);
  byId('progress').hidden = false; byId('progress-fill').style.width = `${percent}%`; byId('progress-text').textContent = `${run.status}: ${finished} of ${all.length} checks (${percent}%)`;
  const execution = run.execution || {};
  const mode = String(run.run_mode || execution.mode || 'balanced');
  const eta = execution.eta_seconds == null ? '' : ` · ETA about ${formatDuration(execution.eta_seconds)}`;
  const queue = execution.total == null ? '' : ` · marketplace checks ${execution.finished || 0}/${execution.total}`;
  byId('progress-detail').textContent = `${mode[0].toUpperCase()}${mode.slice(1)} · ${execution.phase_label || (run.status === 'RUNNING' ? 'Monitoring sources' : 'Monitoring complete')}${queue}${eta}`;
  const activity = execution.current_activity;
  byId('progress-activity').textContent = activity ? `${activity.marketplace} · ${activity.model} · ${uiText(activity.message)}` : run.status === 'RUNNING' ? uiText('Preparing the next marketplace check…') : '';
  renderQueueProgress(execution);
  const actionText = `${actionRequired ? ` · Action required ${actionRequired}` : ''}${cooldown ? ` · Cooldown ${cooldown}` : ''}${cached ? ` · Cached ${cached}` : ''}`;
  const stopped = run.status === 'INCOMPLETE';
  byId('run-state').textContent = run.status === 'RUNNING' ? `Monitoring… Success ${success} · Not found ${notFound} · Failed ${failed}${actionText}` : `${stopped ? 'Stopped' : 'Completed'} · Success ${success} · Not found ${notFound} · Failed ${failed}${actionText}`;
  const includeNotFound = byId('retry-include-not-found').checked;
  const retryable = state.tasks.filter(task => task.retry_class === 'transient' || (includeNotFound && task.status === 'NOT_FOUND'));
  const salidziniRetryable = retryable.some(task => task.marketplace_key === 'salidzini');
  byId('start-run').disabled = run.status === 'RUNNING'; byId('run-mode').disabled = run.status === 'RUNNING'; byId('clear-run').disabled = !(state.tasks.length || state.shopResults.length); byId('retry-unresolved').disabled = run.status === 'RUNNING' || !retryable.length; byId('retry-salidzini').disabled = run.status === 'RUNNING' || !salidziniRetryable; byId('test-salidzini').disabled = run.status === 'RUNNING' || !salidziniRetryable; byId('retry-marketplace').disabled = run.status === 'RUNNING'; byId('retry-limit').disabled = run.status === 'RUNNING'; byId('retry-include-not-found').disabled = run.status === 'RUNNING'; byId('export-run').disabled = run.status === 'RUNNING' || !(state.tasks.length || state.shopResults.length); byId('stop-run').hidden = run.status !== 'RUNNING'; byId('stop-run').disabled = false; if (resultsChanged) renderResults(); renderActionRequired(run);
  if (run.status !== 'RUNNING') {
    if (state.runPoll) { clearTimeout(state.runPoll); state.runPoll = null; }
    if (previousStatus !== run.status) { loadExports(); loadMonitoringHistory(); }
  }
}

async function pollRun(runId) {
  try { const run = await api(`/runs/${runId}`); renderRun(run); return run; }
  catch (error) { if (!state.stopRequested) showBanner('error', error.message); return null; }
}
function pollingDelay() {
  const total = state.tasks.length + state.shopResults.length;
  return total >= 600 ? 6000 : total >= 300 ? 4000 : 2000;
}
function scheduleRunPolling(runId, delay = pollingDelay()) {
  if (state.runPoll) clearTimeout(state.runPoll);
  state.runPoll = window.setTimeout(async () => {
    state.runPoll = null;
    const run = await pollRun(runId);
    if (run?.status === 'RUNNING' && !state.stopRequested) scheduleRunPolling(runId);
  }, delay);
}
async function refreshOneModel(event) {
  const button = event.target.closest('[data-refresh-model]');
  if (!button || !state.currentRunId) return;
  button.disabled = true; button.classList.add('spinning');
  try {
    const result = await api(`/runs/${encodeURIComponent(state.currentRunId)}/models/${button.dataset.refreshModel}/retry`, { method: 'POST' });
    showBanner('success', result.checks_started ? `Refreshing ${result.checks_started} enabled checks for this model.` : 'No enabled marketplace checks are available for this model.');
    await pollRun(state.currentRunId);
    if (result.checks_started) {
      scheduleRunPolling(state.currentRunId, 1000);
    }
  } catch (error) { button.disabled = false; button.classList.remove('spinning'); showBanner('error', error.message); }
}

async function loadMonitoringHistory() {
  if (state.historyLoading) return;
  state.historyLoading = true;
  try {
    const runs = await api('/monitoring-history?limit=20');
    byId('monitoring-history').classList.remove('muted');
    const renderHistoryRow = run => {
      const checks = Number(run.shop_checks || 0) + Number(run.assisted_checks || 0);
      const current = run.run_id === state.currentRunId ? ' current' : '';
      const mode = String(run.run_mode || 'balanced');
      return `<div class="history-row${current}"><div><strong>${escapeHtml(new Date(run.created_at).toLocaleString(uiLocale()))}</strong><span>${badge(run.status, statusClass(run.status))} · ${escapeHtml(mode[0].toUpperCase() + mode.slice(1))} · ${checks} marketplace checks</span></div><button type="button" class="compact secondary" data-open-run="${escapeHtml(run.run_id)}">${current ? 'Opened' : 'Open run'}</button></div>`;
    };
    const recent = runs.slice(0, 3); const older = runs.slice(3);
    byId('monitoring-history').innerHTML = runs.length ? `${recent.map(renderHistoryRow).join('')}${older.length ? `<details class="history-older"><summary>Show ${older.length} older runs</summary><div class="history-list">${older.map(renderHistoryRow).join('')}</div></details>` : ''}` : '<span class="muted">No monitoring runs yet.</span>';
  } catch (error) { byId('monitoring-history').classList.add('muted'); byId('monitoring-history').textContent = `History unavailable: ${error.message}`; }
  finally { state.historyLoading = false; }
}

async function openHistoryRun(event) {
  const button = event.target.closest('[data-open-run]');
  if (!button) return;
  if (state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; }
  button.disabled = true; button.textContent = 'Opening…';
  try { await pollRun(button.dataset.openRun); await loadMonitoringHistory(); }
  catch (error) { showBanner('error', error.message); }
}

async function startRun() {
  byId('start-run').disabled = true; byId('run-mode').disabled = true; byId('retry-unresolved').disabled = true; byId('export-run').disabled = true; state.stopRequested = false; state.resultFilterInitialized = false; state.resultRenderSignature = ''; state.lastActionSignature = ''; state.actionRenderSignature = ''; Object.values(state.resultFilters).forEach(filter => filter.clear()); Object.values(state.resultFilterKnown).forEach(filter => filter.clear());
  const mode = byId('run-mode').value;
  try { const result = await api('/runs', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ mode }) }); await pollRun(result.run_id); await loadMonitoringHistory(); scheduleRunPolling(result.run_id); }
  catch (error) { byId('start-run').disabled = false; byId('run-mode').disabled = false; showBanner('error', error.message); }
}

async function hardStopRun() {
  if (!state.currentRunId || !window.confirm(uiText('Stop the current monitoring run immediately? Completed results will be kept.'))) return;
  const button = byId('stop-run'); button.disabled = true; button.textContent = 'Stopping…'; state.stopRequested = true;
  try {
    if (state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; }
    const run = await api(`/runs/${encodeURIComponent(state.currentRunId)}/stop`, { method: 'POST' });
    renderRun(run); showBanner('success', 'Monitoring stopped. You can start a new run.');
  } catch (error) {
    state.stopRequested = false; button.disabled = false; showBanner('error', error.message);
  } finally { button.textContent = '■ Hard stop'; }
}

async function clearCurrentTable() {
  if (!state.currentRunId || byId('clear-run').disabled) return;
  byId('clear-run-popover').hidden = true;
  const button = byId('clear-run'); button.disabled = true; button.textContent = 'Clearing…'; state.stopRequested = true;
  try {
    if (state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; }
    const run = await api(`/runs/${encodeURIComponent(state.currentRunId)}/clear`, { method: 'POST' });
    state.resultFilterInitialized = false; state.lastActionSignature = ''; state.actionRenderSignature = '';
    Object.values(state.resultFilters).forEach(filter => filter.clear());
    Object.values(state.resultFilterKnown).forEach(filter => filter.clear());
    renderRun(run); showBanner('success', 'Current monitoring table and verification requests were cleared.');
  } catch (error) {
    state.stopRequested = false; button.disabled = false; showBanner('error', error.message);
  } finally { button.textContent = 'Clear table'; }
}

async function retryUnresolved(marketplaceOverride = null) {
  if (!state.currentRunId || byId('retry-unresolved').disabled) return;
  const sourceKey = typeof marketplaceOverride === 'string' ? marketplaceOverride : byId('retry-marketplace').value;
  const button = sourceKey === 'salidzini' ? byId('retry-salidzini') : byId('retry-unresolved');
  const originalText = button.textContent; button.disabled = true; button.textContent = 'Retrying…';
  try {
    const result = await api(`/runs/${encodeURIComponent(state.currentRunId)}/retry-unresolved`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ include_not_found: byId('retry-include-not-found').checked,
        marketplace_key: sourceKey, limit: Number(byId('retry-limit').value) })
    });
    showBanner('success', result.checks_started ? `${result.checks_started} unresolved checks queued.` : 'No unresolved checks matched the selected sources.');
    await pollRun(state.currentRunId);
    if (result.checks_started) scheduleRunPolling(state.currentRunId, 700);
  } catch (error) { showBanner('error', error.message); }
  finally { button.textContent = originalText; }
}

async function testSalidziniSession() {
  if (!state.currentRunId || byId('test-salidzini').disabled) return;
  const button = byId('test-salidzini'); button.disabled = true;
  try {
    const result = await api(`/runs/${encodeURIComponent(state.currentRunId)}/salidzini/health-check`, {method:'POST'});
    showBanner('success', result.checks_started ? `Testing Salidzini with ${result.model}.` : result.detail);
    if (result.checks_started) scheduleRunPolling(state.currentRunId,700);
  } catch (error) { showBanner('error',error.message); }
}

function exportCurrentRun() {
  if (!state.currentRunId || byId('export-run').disabled) return;
  const link = document.createElement('a');
  link.href = `/runs/${encodeURIComponent(state.currentRunId)}/export`;
  link.download = '';
  document.body.appendChild(link); link.click(); link.remove();
  showBanner('success', 'Excel export started. The summary is fitted to one printed page horizontally.');
}

async function loadExports() {
  try { const items = await api('/exports?limit=6'); byId('exports').innerHTML = items.length ? items.map(item => `<div class="export-line"><a href="/exports/file/${encodeURIComponent(item.filename)}">${escapeHtml(item.filename)}</a> · ${Math.round(item.size_bytes / 1024)} KB</div>`).join('') : 'No exports yet.'; }
  catch { byId('exports').textContent = 'Exports are unavailable.'; }
}
async function loadLogs() {
  try { const items = await api('/logs?limit=8'); byId('logs').innerHTML = items.length ? items.map(item => `<div class="log-line">[${escapeHtml(item.level)}] ${escapeHtml(item.message)}</div>`).join('') : 'No activity yet.'; }
  catch { byId('logs').textContent = 'Activity log is unavailable.'; }
}

function openCatalogClear(kind) {
  const dialog = byId('catalog-clear-dialog');
  byId('catalog-clear-form').dataset.kind = kind;
  byId('catalog-clear-title').textContent = kind === 'source' ? 'Clear monitoring models?' : 'Clear warehouse stock?';
  byId('catalog-clear-description').textContent = kind === 'source'
    ? 'These models will be excluded from future monitoring. Warehouse stock stays unchanged.'
    : 'Warehouse rows will be removed from the active stock table. All monitoring models remain enabled, even when their stock is removed.';
  byId('catalog-clear-error').hidden = true;
  dialog.showModal();
}

async function clearCatalog(event) {
  event.preventDefault();
  const form = event.currentTarget; const kind = form.dataset.kind;
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const result = await api(`/catalog/clear/${kind}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({confirm:true})});
    byId('catalog-clear-dialog').close();
    state.catalogStates[kind] = new Set(['active','paused']);
    initializeCatalogFilters();
    await Promise.all([loadCatalog(), loadSetupStatus()]);
    showBanner('success', `${result.moved_to_trash} rows moved to Trash. Run history was kept.`);
  } catch (error) {
    byId('catalog-clear-error').textContent = error.message;
    byId('catalog-clear-error').hidden = false;
  } finally { button.disabled = false; }
}

function wireEvents() {
  byId('browser-bridge-state').addEventListener('click', async event => {
    const button = event.target.closest('[data-switch-client]'); if (!button) return;
    button.disabled = true;
    try { await api('/browser-bridge/active-client',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({client_id:button.dataset.switchClient})}); await loadBrowserBridge(); showBanner('success','Active browser switched. New capture jobs will use this browser.'); }
    catch (error) { button.disabled = false; showBanner('error',error.message); }
  });
  document.addEventListener('keydown', event => {
    if (!byId('action-dialog').open || /INPUT|SELECT|TEXTAREA/.test(event.target.tagName)) return;
    const item = byId('action-items').querySelector('.action-item');
    if (!item) return;
    const target = event.key === '1' || event.key === '2'
      ? item.querySelector(`[data-check-action="accept-candidate"][data-candidate-index="${Number(event.key)-1}"]`)
      : event.key === '0' ? item.querySelector('[data-check-action="toggle-not-found"]') : null;
    if (target) { event.preventDefault(); target.click(); }
  });
  document.querySelectorAll('[data-clear-catalog]').forEach(button => button.addEventListener('click', () => openCatalogClear(button.dataset.clearCatalog)));
  document.querySelectorAll('[data-cancel-catalog-clear]').forEach(button => button.addEventListener('click', () => byId('catalog-clear-dialog').close()));
  byId('catalog-clear-form').addEventListener('submit', clearCatalog);
  byId('result-rows').addEventListener('click', async event => {
    const undo = event.target.closest('[data-undo-review]');
    if (undo) {
      try {
        await api(`/runs/${encodeURIComponent(state.currentRunId)}/marketplaces/${undo.dataset.item}/${encodeURIComponent(undo.dataset.key)}/undo`, {method:'POST'});
        await pollRun(state.currentRunId); showBanner('success','Last review decision restored.');
      } catch (error) { showBanner('error', error.message); }
      return;
    }
    const button = event.target.closest('[data-remove-offer]');
    if (!button) return;
    if (!window.confirm(uiText('Remove this false match from the current run?'))) return;
    try {
      await api(`/runs/${encodeURIComponent(state.currentRunId)}/marketplaces/${button.dataset.item}/${encodeURIComponent(button.dataset.key)}/offers/${button.dataset.removeOffer}`, {method:'DELETE'});
      await pollRun(state.currentRunId);
    } catch (error) { showBanner('error', error.message); }
  });
  initializeCatalogFilters(); document.querySelectorAll('[data-add]').forEach(button => button.addEventListener('click', () => openEditor(button.dataset.add)));
  byId('source-rows').addEventListener('click', handleItemAction); byId('stock-rows').addEventListener('click', handleItemAction); byId('item-form').addEventListener('submit', saveItem);
  byId('dialog-close').addEventListener('click', () => byId('item-dialog').close()); byId('dialog-cancel').addEventListener('click', () => byId('item-dialog').close());
  byId('action-close').addEventListener('click', () => byId('action-dialog').close()); byId('action-later').addEventListener('click', () => byId('action-dialog').close());
  byId('correction-close').addEventListener('click', () => byId('correction-dialog').close()); byId('correction-cancel').addEventListener('click', () => byId('correction-dialog').close());
  byId('correction-not-found').addEventListener('click', () => saveResultCorrection('NOT_FOUND'));
  byId('correction-form').addEventListener('submit', event => { event.preventDefault(); saveResultCorrection('SUCCESS'); });
  byId('method-test-close').addEventListener('click', () => byId('method-test-dialog').close()); byId('method-test-cancel').addEventListener('click', () => byId('method-test-dialog').close()); byId('method-test-run').addEventListener('click', runMethodTest);
  byId('review-actions').addEventListener('click', () => { if (!byId('action-dialog').open) byId('action-dialog').showModal(); }); byId('action-items').addEventListener('click', handleActionDialog);
  byId('result-rows').addEventListener('click', refreshOneModel); byId('result-rows').addEventListener('click', openResultCorrection); byId('monitoring-history').addEventListener('click', openHistoryRun); byId('refresh-history').addEventListener('click', loadMonitoringHistory);
  document.addEventListener('click', event => { const button = event.target.closest('[data-copy-model],[data-copy-input]'); if (button && !button.closest('#action-items')) copyModel(button); });
  byId('workbook-file').addEventListener('change', event => updateFileName(event.target)); byId('stock-file').addEventListener('change', event => updateFileName(event.target));
  byId('workbook-upload').addEventListener('click', () => upload('workbook')); byId('stock-upload').addEventListener('click', () => upload('stock')); byId('start-run').addEventListener('click', startRun); byId('clear-run').addEventListener('click', event => { event.stopPropagation(); if (!byId('clear-run').disabled) byId('clear-run-popover').hidden = false; }); byId('clear-run-cancel').addEventListener('click', () => { byId('clear-run-popover').hidden = true; }); byId('clear-run-confirm').addEventListener('click', clearCurrentTable); byId('retry-unresolved').addEventListener('click', () => retryUnresolved()); byId('retry-salidzini').addEventListener('click', () => retryUnresolved('salidzini')); byId('test-salidzini').addEventListener('click', testSalidziniSession); byId('retry-include-not-found').addEventListener('change', () => { if (state.currentRunId) pollRun(state.currentRunId); }); byId('stop-run').addEventListener('click', hardStopRun); byId('export-run').addEventListener('click', exportCurrentRun);
  document.addEventListener('click', event => { if (!event.target.closest('.run-clear-control')) byId('clear-run-popover').hidden = true; });
  byId('run-mode').addEventListener('change', updateRunModeHelp);
  byId('marketplace-master').addEventListener('change', event => updateMaster('marketplace', event.target.checked)); byId('shop-master').addEventListener('change', event => updateMaster('shop', event.target.checked));
  for (const kind of ['source', 'stock']) { let timer; byId(`${kind}-search`).addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => loadKind(kind).catch(error => showBanner('error', error.message)), 220); }); }
}

async function initialize() {
  const savedMode = localStorage.getItem(RUN_MODE_KEY); if (RUN_MODE_HELP[savedMode]) byId('run-mode').value = savedMode; updateRunModeHelp();
  wireEvents();
  try {
    const [health] = await Promise.all([api('/health'), loadSources()]); byId('service-state').textContent = `v${health.version} · marketplace engine ready`; byId('service-state').classList.add('ok');
    const policy = health.polite_monitoring; if (policy) byId('polite-mode-state').textContent = 'Marketplace-only · 1 request per marketplace at a time · 3 s Kaina/Hinnavaatlus · 12 s Salidzini · automatic protection pause · manual entry available';
    await Promise.all([loadCatalog(), loadSetupStatus(), loadExports(), loadLogs(), loadBrowserBridge(), loadMonitoringHistory()]); try { const latest = await api('/runs/latest'); renderRun(latest); if (latest.status === 'RUNNING') scheduleRunPolling(latest.id || latest.run_id); await loadMonitoringHistory(); } catch { renderResults(); }
    setInterval(loadLogs, 10000); setInterval(loadBrowserBridge, 5000);
  } catch (error) { byId('service-state').textContent = 'Startup error'; showBanner('error', error.message); }
}

initialize();
