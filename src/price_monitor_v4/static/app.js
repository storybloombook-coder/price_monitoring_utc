const byId = id => document.getElementById(id);
const HIDDEN_COLUMNS_KEY = 'price-monitor-v4.hidden-columns';
const state = {
  source: [], sourceOptions: [], stock: [], summary: null, sources: [], tasks: [], shopResults: [], runPoll: null,
  catalogStates: { source: new Set(['active', 'paused']), stock: new Set(['active', 'paused']) },
  resultFilters: { model: new Set(), status: new Set(), marketplace: new Set(), shop: new Set() },
  resultFilterInitialized: false,
  hiddenColumns: new Set(JSON.parse(localStorage.getItem(HIDDEN_COLUMNS_KEY) || '[]'))
};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data?.detail || data || `Request failed (${response.status})`);
  return data;
}

function showBanner(kind, message) {
  const error = byId('error-banner');
  const success = byId('success-banner');
  error.hidden = true; success.hidden = true;
  if (!message) return;
  const target = kind === 'error' ? error : success;
  target.textContent = message; target.hidden = false;
  window.setTimeout(() => { target.hidden = true; }, 5000);
}

function badge(label, type) { return `<span class="badge ${escapeHtml(type)}">${escapeHtml(label)}</span>`; }
function statusClass(value) { return String(value || '').toLowerCase().replaceAll('_', '-'); }

function itemStatus(item) {
  if (item.state === 'trash') return badge('Trash', 'trash');
  if (item.paused) return badge('Paused', 'paused');
  return badge('Active', 'active');
}

function actionButtons(item) {
  if (item.state === 'trash') return `<button class="link-action" data-action="restore" data-id="${item.id}">Restore</button>`;
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
  byId('stock-rows').innerHTML = items.length ? items.map(item => `<tr><td><span class="item-primary">${escapeHtml(item.nomenclature)}</span>
    <span class="item-secondary">${escapeHtml(item.model || 'No linked model')} · ${escapeHtml(item.warehouse || 'No warehouse')}</span></td>
    <td>${Number(item.quantity || 0).toLocaleString('en-US')} units<span class="item-secondary">${Number(item.unit_cost_eur || 0).toFixed(2)} EUR</span></td>
    <td>${itemStatus(item)} ${item.state !== 'trash' && !item.matched ? badge('Unmatched', 'unmatched') : ''}</td><td>${actionButtons(item)}</td></tr>`).join('')
    : '<tr><td colspan="4" class="empty">No positions found.</td></tr>';
}

function renderSummary() {
  if (!state.summary) return;
  const s = state.summary.source; const w = state.summary.stock;
  byId('catalog-summary').textContent = `Source: ${s.active} active, ${s.paused} paused · Stock: ${w.active} active, ${w.unmatched} unmatched`;
  byId('source-model-options').innerHTML = state.sourceOptions.filter(item => item.state !== 'trash').map(item => `<option value="${escapeHtml(item.model)}"></option>`).join('');
}

function renderMultiFilter(id, options, selected, onChange, emptyText = 'No options') {
  const root = byId(id); const menu = root.querySelector('.filter-menu');
  menu.innerHTML = options.length ? options.map(option => `<label><input type="checkbox" value="${escapeHtml(option.value)}" ${selected.has(option.value) ? 'checked' : ''}> ${escapeHtml(option.label)}</label>`).join('') : `<span class="muted">${emptyText}</span>`;
  menu.querySelectorAll('input').forEach(input => input.addEventListener('change', () => {
    if (input.checked) selected.add(input.value); else selected.delete(input.value);
    root.querySelector('summary').dataset.count = selected.size;
    onChange();
  }));
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
  return `<div class="source-item ${item.master_enabled ? '' : 'master-disabled'}"><a href="${escapeHtml(item.base_url)}" target="_blank" rel="noopener">${escapeHtml(item.name)}</a>
    <label class="switch-row" aria-label="Enable ${escapeHtml(item.name)}"><input type="checkbox" data-source-key="${escapeHtml(item.key)}" ${item.enabled ? 'checked' : ''} ${item.master_enabled ? '' : 'disabled'}><span class="switch"></span></label></div>`;
}

function renderSources() {
  const marketplaces = state.sources.filter(item => item.kind === 'marketplace');
  const shops = state.sources.filter(item => item.kind === 'shop');
  byId('marketplace-master').checked = marketplaces[0]?.master_enabled ?? true;
  byId('shop-master').checked = shops[0]?.master_enabled ?? true;
  byId('marketplace-list').innerHTML = marketplaces.map(sourceSwitch).join('');
  const countries = ['Lithuania', 'Latvia', 'Estonia'];
  byId('shop-list').innerHTML = countries.map(country => {
    const items = shops.filter(item => item.country === country);
    return `<div class="country-block"><span class="country-name">${country}</span><div class="country-shops">${items.length ? items.map(sourceSwitch).join('') : '<span class="muted">No shops configured yet.</span>'}</div></div>`;
  }).join('');
  byId('shop-link-inputs').innerHTML = shops.map(item => `<label>${escapeHtml(item.name)}<input data-shop-link="${escapeHtml(item.key)}" type="url" placeholder="${escapeHtml(item.base_url)}product…"></label>`).join('');
  document.querySelectorAll('[data-source-key]').forEach(input => input.addEventListener('change', () => updateSource(input.dataset.sourceKey, input.checked)));
}

async function loadSources() { state.sources = await api('/sources'); renderSources(); if (state.tasks.length || state.shopResults.length) renderResults(); }
async function updateSource(key, enabled) {
  try { await api(`/sources/${encodeURIComponent(key)}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled }) }); await loadSources(); }
  catch (error) { showBanner('error', error.message); await loadSources(); }
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
  } else {
    byId('stock-name').value = item?.nomenclature || ''; byId('stock-model').value = item?.model || ''; byId('stock-warehouse').value = item?.warehouse || '';
    byId('stock-quantity').value = item?.quantity ?? 0; byId('stock-cost').value = item?.unit_cost_eur ?? 0;
  }
  byId('item-dialog').showModal();
}

async function saveItem(event) {
  event.preventDefault(); const kind = byId('item-kind').value; const id = byId('item-id').value;
  const shopLinks = Object.fromEntries([...document.querySelectorAll('[data-shop-link]')].map(input => [input.dataset.shopLink, input.value.trim()]));
  const payload = kind === 'source' ? { model: byId('source-model').value, source_sheets: [...document.querySelectorAll('[name="source-sheet"]:checked')].map(input => input.value), shop_links: shopLinks, paused: byId('item-paused').checked }
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
    await loadCatalog(); await loadSetupStatus();
  } catch (error) { showBanner('error', error.message); }
}

async function upload(kind) {
  const input = byId(kind === 'workbook' ? 'workbook-file' : 'stock-file'); const button = byId(kind === 'workbook' ? 'workbook-upload' : 'stock-upload');
  if (!input.files[0]) return showBanner('error', 'Choose an Excel file first.');
  const form = new FormData(); form.append('file', input.files[0]); button.disabled = true;
  try {
    const result = await api(kind === 'workbook' ? '/workbook/upload' : '/stock/upload', { method: 'POST', body: form }); input.value = '';
    await Promise.all([loadCatalog(), loadSetupStatus()]); showBanner('success', `Imported ${result.models_found ?? result.imported} positions.`);
  } catch (error) { showBanner('error', error.message); } finally { button.disabled = false; }
}

async function loadSetupStatus() {
  const [workbook, stock] = await Promise.all([api('/workbook'), api('/stock')]);
  byId('workbook-status').textContent = `${workbook.models_found} models · ${workbook.source_workbook}`;
  byId('stock-status').textContent = `${stock.count} items · ${stock.matched} linked to models`;
}

function euro(value) { return value == null ? '—' : `${Number(value).toFixed(2)} EUR`; }
function offerLink(offer) {
  if (!offer) return '—'; const label = `${euro(offer.price_eur)}${offer.store ? ` · ${escapeHtml(offer.store)}` : ''}`;
  return offer.url ? `<a href="${escapeHtml(offer.url)}" target="_blank" rel="noopener">${label}</a>` : label;
}

function aggregateResults() {
  const rows = new Map();
  const ensure = (model, canonical = '') => {
    const key = String(canonical || model || '').trim().toUpperCase();
    if (!rows.has(key)) rows.set(key, { key, model: model || canonical, tasks: [], shops: {}, stockQuantity: null, stockCost: null });
    return rows.get(key);
  };
  state.tasks.forEach(task => {
    const row = ensure(task.source_model || task.canonical_model, task.canonical_model); row.tasks.push(task);
    if (task.stock_quantity != null) row.stockQuantity = task.stock_quantity; if (task.stock_unit_cost_eur != null) row.stockCost = task.stock_unit_cost_eur;
  });
  state.shopResults.forEach(result => { ensure(result.model, result.model).shops[result.shop_key] = result; });
  state.sourceOptions.filter(item => !item.paused && item.state !== 'trash').forEach(item => ensure(item.model, item.canonical_model));
  return [...rows.values()].sort((a, b) => a.model.localeCompare(b.model, undefined, { numeric: true }));
}

function rowStatus(row) {
  const statuses = [...row.tasks.map(item => item.status), ...Object.values(row.shops).map(item => item.status)];
  if (statuses.some(value => ['RUNNING', 'PENDING'].includes(value))) return 'RUNNING';
  if (statuses.some(value => value === 'SUCCESS')) return 'SUCCESS';
  if (statuses.some(value => value === 'FAILED')) return 'FAILED';
  if (statuses.some(value => value === 'INCOMPLETE')) return 'INCOMPLETE';
  return statuses.length ? 'NOT_FOUND' : 'NOT_STARTED';
}

function lowestOffer(row, field) {
  return row.tasks.map(task => task[field]).filter(Boolean).sort((a, b) => Number(a.price_eur) - Number(b.price_eur))[0] || null;
}

function marketplaceCell(row) {
  if (!row.tasks.length) return '—';
  const cheapest = lowestOffer(row, 'cheapest_in_stock') || lowestOffer(row, 'cheapest_pre_order');
  const details = row.tasks.map(task => `<div class="detail-offer"><strong>${escapeHtml(task.marketplace)}</strong>${badge(task.status, statusClass(task.status))}<span>${escapeHtml(task.matched_title || 'No matching title')}</span><span>${offerLink(task.cheapest_in_stock || task.cheapest_pre_order)}</span>${task.error ? `<span class="detail-error">${escapeHtml(task.error)}</span>` : ''}</div>`).join('');
  return `<details class="cell-details"><summary>${cheapest ? offerLink(cheapest) : `${row.tasks.length} result${row.tasks.length === 1 ? '' : 's'}`}</summary>${details}</details>`;
}

function shopCell(row, shop) {
  const item = row.shops[shop.key];
  if (!shop.effective_enabled && !item) return '<span class="muted">Disabled</span>';
  if (!item) return '—';
  const link = item.product_url || item.search_url; const summary = item.status === 'SUCCESS' ? euro(item.price_eur) : item.status === 'PENDING' ? 'Checking…' : item.status.replaceAll('_', ' ');
  return `<details class="cell-details"><summary>${badge(summary, statusClass(item.status))}</summary><div class="detail-offer"><span>${escapeHtml(item.availability || 'Availability unknown')}</span>${link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">Open ${escapeHtml(item.product_url ? 'product' : 'search')}</a>` : ''}${item.checked_at ? `<span class="muted">Checked ${escapeHtml(new Date(item.checked_at).toLocaleString('en-GB'))}</span>` : ''}${item.error ? `<span class="detail-error">${escapeHtml(item.error)}</span>` : ''}</div></details>`;
}

function columns() {
  const shops = state.sources.filter(item => item.kind === 'shop');
  return [
    { key: 'model', label: 'Model' }, { key: 'marketplaces', label: 'Marketplaces' }, { key: 'lowest-stock', label: 'Lowest in-stock' }, { key: 'lowest-preorder', label: 'Lowest pre-order' },
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
    marketplace: state.sources.filter(item => item.kind === 'marketplace').map(item => ({ value: item.key, label: item.name })),
    shop: state.sources.filter(item => item.kind === 'shop').map(item => ({ value: item.key, label: item.name }))
  };
  for (const [kind, options] of Object.entries(values)) {
    if (!state.resultFilterInitialized) options.forEach(option => state.resultFilters[kind].add(option.value));
    else {
      const allowed = new Set(options.map(option => option.value));
      [...state.resultFilters[kind]].filter(value => !allowed.has(value)).forEach(value => state.resultFilters[kind].delete(value));
    }
    renderMultiFilter(`${kind}-filter`, options, state.resultFilters[kind], renderResults);
  }
  state.resultFilterInitialized = true;
}

function resultRowVisible(row) {
  if (!state.resultFilters.model.has(row.key) || !state.resultFilters.status.has(rowStatus(row))) return false;
  const marketplaceKeys = row.tasks.map(task => String(task.marketplace || '').toLowerCase());
  if (marketplaceKeys.length && ![...state.resultFilters.marketplace].some(key => marketplaceKeys.some(name => name.includes(key)))) return false;
  const shopKeys = Object.keys(row.shops);
  if (shopKeys.length && !shopKeys.some(key => state.resultFilters.shop.has(key))) return false;
  return true;
}

function renderResults() {
  const rows = aggregateResults(); buildResultFilters(rows); const cols = columns();
  byId('result-head').innerHTML = cols.map(col => `<th data-col="${escapeHtml(col.key)}" class="${state.hiddenColumns.has(col.key) ? 'col-hidden' : ''}">${escapeHtml(col.label)}<button class="eye-button" data-hide-column="${escapeHtml(col.key)}" title="Hide ${escapeHtml(col.label)}" aria-label="Hide ${escapeHtml(col.label)}">◉</button></th>`).join('');
  renderMultiFilter('column-filter', cols.map(col => ({ value: col.key, label: col.label })), new Set(cols.filter(col => !state.hiddenColumns.has(col.key)).map(col => col.key)), () => {});
  byId('column-filter').querySelectorAll('input').forEach(input => input.addEventListener('change', () => setColumnHidden(input.value, !input.checked)));
  byId('result-head').querySelectorAll('[data-hide-column]').forEach(button => button.addEventListener('click', event => { event.stopPropagation(); setColumnHidden(button.dataset.hideColumn, true); }));
  const cell = (key, content, extra = '') => `<td data-col="${key}" class="${extra} ${state.hiddenColumns.has(key) ? 'col-hidden' : ''}">${content}</td>`;
  byId('result-rows').innerHTML = rows.length ? rows.map(row => {
    const stockOffer = lowestOffer(row, 'cheapest_in_stock'); const preorderOffer = lowestOffer(row, 'cheapest_pre_order');
    const best = stockOffer || preorderOffer; const margin = best && row.stockCost != null ? Number(best.price_eur) - Number(row.stockCost) : null;
    const shopCells = state.sources.filter(item => item.kind === 'shop').map(shop => cell(`shop-${shop.key}`, shopCell(row, shop), 'shop-cell')).join('');
    return `<tr class="${resultRowVisible(row) ? '' : 'result-row-filtered'}">${cell('model', escapeHtml(row.model), 'model-cell')}${cell('marketplaces', marketplaceCell(row), 'source-cell')}${cell('lowest-stock', offerLink(stockOffer))}${cell('lowest-preorder', offerLink(preorderOffer))}${shopCells}${cell('stock', row.stockQuantity == null ? '—' : `${escapeHtml(row.stockQuantity)} / ${euro(row.stockCost)}`)}${cell('margin', margin == null ? '—' : `${margin >= 0 ? '+' : ''}${margin.toFixed(2)} EUR`)}${cell('status', badge(rowStatus(row), statusClass(rowStatus(row))))}</tr>`;
  }).join('') : `<tr><td colspan="${cols.length}" class="empty">No monitoring results yet.</td></tr>`;
}

function renderRun(run) {
  state.tasks = run.tasks || []; state.shopResults = run.shop_results || [];
  const all = [...state.tasks, ...state.shopResults]; const finished = all.filter(item => !['RUNNING', 'PENDING'].includes(item.status)).length;
  const percent = all.length ? Math.round(finished / all.length * 100) : (run.status === 'COMPLETE' ? 100 : 0);
  byId('progress').hidden = false; byId('progress-fill').style.width = `${percent}%`; byId('progress-text').textContent = `${run.status}: ${finished} of ${all.length} checks (${percent}%)`;
  byId('run-state').textContent = run.status === 'RUNNING' ? 'Monitoring in progress…' : 'Latest monitoring completed.'; byId('start-run').disabled = run.status === 'RUNNING'; renderResults();
  if (run.status !== 'RUNNING' && state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; loadExports(); }
}

async function pollRun(runId) { try { renderRun(await api(`/runs/${runId}`)); } catch (error) { showBanner('error', error.message); } }
async function startRun() {
  byId('start-run').disabled = true; state.resultFilterInitialized = false; Object.values(state.resultFilters).forEach(filter => filter.clear());
  try { const result = await api('/runs', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' }); await pollRun(result.run_id); if (state.runPoll) clearInterval(state.runPoll); state.runPoll = setInterval(() => pollRun(result.run_id), 2000); }
  catch (error) { byId('start-run').disabled = false; showBanner('error', error.message); }
}

async function loadExports() {
  try { const items = await api('/exports?limit=6'); byId('exports').innerHTML = items.length ? items.map(item => `<div class="export-line"><a href="/exports/file/${encodeURIComponent(item.filename)}">${escapeHtml(item.filename)}</a> · ${Math.round(item.size_bytes / 1024)} KB</div>`).join('') : 'No exports yet.'; }
  catch { byId('exports').textContent = 'Exports are unavailable.'; }
}
async function loadLogs() {
  try { const items = await api('/logs?limit=8'); byId('logs').innerHTML = items.length ? items.map(item => `<div class="log-line">[${escapeHtml(item.level)}] ${escapeHtml(item.message)}</div>`).join('') : 'No activity yet.'; }
  catch { byId('logs').textContent = 'Activity log is unavailable.'; }
}

function wireEvents() {
  initializeCatalogFilters(); document.querySelectorAll('[data-add]').forEach(button => button.addEventListener('click', () => openEditor(button.dataset.add)));
  byId('source-rows').addEventListener('click', handleItemAction); byId('stock-rows').addEventListener('click', handleItemAction); byId('item-form').addEventListener('submit', saveItem);
  byId('dialog-close').addEventListener('click', () => byId('item-dialog').close()); byId('dialog-cancel').addEventListener('click', () => byId('item-dialog').close());
  byId('workbook-upload').addEventListener('click', () => upload('workbook')); byId('stock-upload').addEventListener('click', () => upload('stock')); byId('start-run').addEventListener('click', startRun);
  byId('marketplace-master').addEventListener('change', event => updateMaster('marketplace', event.target.checked)); byId('shop-master').addEventListener('change', event => updateMaster('shop', event.target.checked));
  for (const kind of ['source', 'stock']) { let timer; byId(`${kind}-search`).addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => loadKind(kind).catch(error => showBanner('error', error.message)), 220); }); }
}

async function initialize() {
  wireEvents();
  try {
    const [health] = await Promise.all([api('/health'), loadSources()]); byId('service-state').textContent = `v${health.version} · monitoring service ${health.legacy_service}`; byId('service-state').classList.add('ok');
    await Promise.all([loadCatalog(), loadSetupStatus(), loadExports(), loadLogs()]); try { renderRun(await api('/runs/latest')); } catch { renderResults(); }
    setInterval(loadLogs, 10000);
  } catch (error) { byId('service-state').textContent = 'Startup error'; showBanner('error', error.message); }
}

initialize();
