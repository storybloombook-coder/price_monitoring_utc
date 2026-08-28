const byId = id => document.getElementById(id);
const HIDDEN_COLUMNS_KEY = 'price-monitor-v4.hidden-columns';
const SHOP_METHODS = [
  ['auto', 'Auto · gentle fallback'], ['direct', 'Direct request'], ['background', 'Background Edge'],
  ['playwright', 'Playwright Edge'], ['extension', 'Browser extension'], ['manual', 'Manual only']
];
const MARKETPLACE_METHODS = [['auto', 'Auto'], ['legacy', 'Legacy engine']];
const ASSISTED_MARKETPLACE_METHODS = [['auto', 'Assisted · Edge + manual']];
const STATUS_HELP = {
  active: 'Enabled and available for the normal workflow.',
  paused: 'Temporarily excluded from monitoring without deleting the position.',
  trash: 'Moved to trash. It is excluded until restored or permanently deleted.',
  monitoring: 'This stock model is linked to an active model in the monitoring list.',
  unmatched: 'This stock position is not linked to an active monitoring model.',
  success: 'The check completed and returned a usable result.',
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
const state = {
  source: [], sourceOptions: [], stock: [], summary: null, sources: [], tasks: [], shopResults: [], runPoll: null,
  catalogStates: { source: new Set(['active', 'paused']), stock: new Set(['active', 'paused']) },
  resultFilters: { model: new Set(), status: new Set(), marketplace: new Set(), shop: new Set() },
  resultFilterKnown: { model: new Set(), status: new Set(), marketplace: new Set(), shop: new Set() },
  resultFilterInitialized: false,
  currentRunId: null, lastActionSignature: '', actionItems: [], stopRequested: false,
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

function badge(label, type, help = STATUS_HELP[type]) {
  const tooltip = help ? ` title="${escapeHtml(help)}" tabindex="0"` : '';
  return `<span class="badge ${escapeHtml(type)}"${tooltip}>${escapeHtml(label)}</span>`;
}
function statusClass(value) { return String(value || '').toLowerCase().replaceAll('_', '-'); }

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
    <td>${Number(item.quantity || 0).toLocaleString('en-US')} units<span class="item-secondary">${Number(item.unit_cost_eur || 0).toFixed(2)} EUR</span></td>
    <td>${itemStatus(item)} ${item.state !== 'trash' && item.matched ? badge('In monitoring', 'monitoring') : item.state !== 'trash' ? badge('Unmatched', 'unmatched') : ''}</td><td>${actionButtons(item)}</td></tr>`).join('')
    : '<tr><td colspan="4" class="empty">No positions found.</td></tr>';
}

function renderSummary() {
  if (!state.summary) return;
  const s = state.summary.source; const w = state.summary.stock;
  byId('catalog-summary').textContent = `Monitoring: ${s.active} active, ${s.paused} paused · Stock: ${w.active} active, ${w.unmatched} unmatched`;
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
  const methods = item.kind === 'shop' ? SHOP_METHODS : item.key === 'salidzini' ? ASSISTED_MARKETPLACE_METHODS : MARKETPLACE_METHODS;
  const options = methods.map(([value, label]) => `<option value="${value}" ${item.collection_method === value ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('');
  const learned = item.last_success_method ? `<span class="learned-method">Last success: ${escapeHtml(item.last_success_method)}</span>` : '';
  return `<div class="source-item ${item.master_enabled ? '' : 'master-disabled'}"><div class="source-identity"><a href="${escapeHtml(item.base_url)}" target="_blank" rel="noopener">${escapeHtml(item.name)}</a>${learned}</div>
    <div class="source-controls"><select class="method-select" data-source-method="${escapeHtml(item.key)}" aria-label="Collection method for ${escapeHtml(item.name)}">${options}</select>${item.kind === 'shop' ? `<button type="button" class="compact secondary" data-test-source="${escapeHtml(item.key)}">Test</button>` : ''}
    <label class="switch-row" aria-label="Enable ${escapeHtml(item.name)}"><input type="checkbox" data-source-key="${escapeHtml(item.key)}" ${item.enabled ? 'checked' : ''} ${item.master_enabled ? '' : 'disabled'}><span class="switch"></span></label></div></div>`;
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
  byId('marketplace-link-inputs').innerHTML = marketplaces.filter(item => item.key === 'salidzini').map(item => `<label>${escapeHtml(item.name)}<input data-marketplace-link="${escapeHtml(item.key)}" type="url" placeholder="${escapeHtml(item.base_url)}product…"></label>`).join('');
  document.querySelectorAll('[data-source-key]').forEach(input => input.addEventListener('change', () => updateSource(input.dataset.sourceKey, input.checked)));
  document.querySelectorAll('[data-source-method]').forEach(select => select.addEventListener('change', () => updateSourceMethod(select.dataset.sourceMethod, select.value)));
  document.querySelectorAll('[data-test-source]').forEach(button => button.addEventListener('click', () => openMethodTest(button.dataset.testSource)));
}

async function loadSources() { state.sources = await api('/sources'); renderSources(); if (state.tasks.length || state.shopResults.length) renderResults(); }

async function loadBrowserBridge() {
  const root = byId('browser-bridge-state');
  try {
    const bridge = await api('/browser-bridge/status');
    root.classList.toggle('connected', bridge.connected);
    const current = bridge.jobs?.[0];
    const detail = current ? ` · checking ${current.shop_key} for ${current.model}` : '';
    const transport = bridge.transport === 'websocket' ? ' · live channel' : bridge.transport === 'polling' ? ' · recovery polling' : '';
    root.innerHTML = `<span class="bridge-dot"></span><span>${bridge.connected ? `Edge extension connected${transport}${detail}` : 'Edge extension not connected · protected shops will require manual verification'}</span>`;
  } catch {
    root.classList.remove('connected');
    root.innerHTML = '<span class="bridge-dot"></span><span>Edge extension status unavailable</span>';
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
      if (!window.confirm('Delete this position permanently? This cannot be undone.')) return;
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
  if (statuses.some(value => value === 'ACTION_REQUIRED')) return 'ACTION_REQUIRED';
  if (statuses.some(value => value === 'COOLDOWN')) return 'COOLDOWN';
  if (statuses.some(value => value === 'SUCCESS')) return 'SUCCESS';
  if (statuses.some(value => value === 'FAILED')) return 'FAILED';
  if (statuses.some(value => value === 'INCOMPLETE')) return 'INCOMPLETE';
  return statuses.length ? 'NOT_FOUND' : 'NOT_STARTED';
}

function resultCounts(row) {
  const statuses = [...row.tasks.map(item => item.status), ...Object.values(row.shops).map(item => item.status)];
  return {
    success: statuses.filter(value => value === 'SUCCESS').length,
    failed: statuses.filter(value => ['FAILED', 'INCOMPLETE'].includes(value)).length,
    notFound: statuses.filter(value => value === 'NOT_FOUND').length,
    actionRequired: statuses.filter(value => value === 'ACTION_REQUIRED').length,
    cooldown: statuses.filter(value => value === 'COOLDOWN').length,
    cached: [...row.tasks, ...Object.values(row.shops)].filter(item => item.status === 'SUCCESS' && item.cached).length,
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
  const availability = field === 'cheapest_in_stock' ? 'IN_STOCK' : 'PRE_ORDER';
  Object.values(row.shops).filter(item => item.status === 'SUCCESS' && item.availability === availability && item.price_eur != null).forEach(item => offers.push({
    price_eur: item.price_eur, store: item.shop_name || item.shop_key, url: item.product_url || item.search_url
  }));
  return offers.sort((a, b) => Number(a.price_eur) - Number(b.price_eur))[0] || null;
}

function marketplaceCell(row, openDetails) {
  if (!row.tasks.length) return '—';
  const detailKey = `${row.key}:marketplaces`;
  const marketplaceLowest = field => row.tasks.map(task => task[field]).filter(Boolean).sort((a, b) => Number(a.price_eur) - Number(b.price_eur))[0] || null;
  const cheapest = marketplaceLowest('cheapest_in_stock') || marketplaceLowest('cheapest_pre_order');
  const details = row.tasks.map(task => `<div class="detail-offer"><div><strong>${escapeHtml(task.marketplace)}</strong> ${badge(task.status, statusClass(task.status))}</div><span><b>Matched:</b> ${escapeHtml(task.matched_title || 'No matching title')}</span><span><b>In stock:</b> ${offerLink(task.cheapest_in_stock)}</span><span><b>Pre-order:</b> ${offerLink(task.cheapest_pre_order)}</span><span class="muted">Attempts: ${escapeHtml(task.attempts ?? 0)}${task.finished_at ? ` · Checked ${escapeHtml(new Date(task.finished_at).toLocaleString('en-GB'))}` : ''}</span>${task.error ? `<span class="detail-error">${escapeHtml(task.error)}</span>` : ''}</div>`).join('');
  return `<details class="cell-details" data-detail-key="${escapeHtml(detailKey)}" ${openDetails.has(detailKey) ? 'open' : ''}><summary>${cheapest ? offerLink(cheapest) : `${row.tasks.length} result${row.tasks.length === 1 ? '' : 's'}`}</summary>${details}</details>`;
}

function shopCell(row, shop, openDetails) {
  const item = row.shops[shop.key];
  if (!shop.effective_enabled && !item) return `<span class="muted" title="${escapeHtml(STATUS_HELP.disabled)}">Disabled</span>`;
  if (!item) return '—';
  const detailKey = `${row.key}:shop:${shop.key}`;
  const link = item.product_url || item.search_url;
  const retryLabel = item.retry_after ? new Date(item.retry_after).toLocaleString('en-GB') : null;
  const summary = item.status === 'SUCCESS' ? `${euro(item.price_eur)}${item.cached ? ' · cached' : ''}` : item.status === 'PENDING' ? 'Checking…' : item.status === 'COOLDOWN' ? 'Cooldown' : item.status.replaceAll('_', ' ');
  const linkLabel = item.status === 'ACTION_REQUIRED' ? 'Open verification' : `Open ${item.product_url ? 'product' : 'search'}`;
  const attempts = (item.attempts || []).map(attempt => `${attempt.method}: ${attempt.result.toLowerCase()} (${attempt.duration_ms} ms)`).join(' · ');
  return `<details class="cell-details" data-detail-key="${escapeHtml(detailKey)}" ${openDetails.has(detailKey) ? 'open' : ''}><summary>${badge(summary, statusClass(item.status))}</summary><div class="detail-offer"><span>${escapeHtml(item.availability || 'Availability unknown')}</span>${item.collection_method ? `<span><b>Method:</b> ${escapeHtml(item.collection_method)}</span>` : ''}${attempts ? `<span class="muted">${escapeHtml(attempts)}</span>` : ''}${item.cached ? '<span class="cache-note">Cached result — no new retailer request was sent</span>' : ''}${retryLabel ? `<span class="cooldown-note">Retry after ${escapeHtml(retryLabel)}</span>` : ''}${link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(linkLabel)}</a>` : ''}${item.checked_at ? `<span class="muted">Checked ${escapeHtml(new Date(item.checked_at).toLocaleString('en-GB'))}</span>` : ''}${item.error ? `<span class="detail-error">${escapeHtml(item.error)}</span>` : ''}</div></details>`;
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
    const known = state.resultFilterKnown[kind];
    if (!state.resultFilterInitialized) options.forEach(option => state.resultFilters[kind].add(option.value));
    else {
      const allowed = new Set(options.map(option => option.value));
      [...state.resultFilters[kind]].filter(value => !allowed.has(value)).forEach(value => state.resultFilters[kind].delete(value));
      options.filter(option => !known.has(option.value)).forEach(option => state.resultFilters[kind].add(option.value));
    }
    state.resultFilterKnown[kind] = new Set(options.map(option => option.value));
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
    const shopCells = state.sources.filter(item => item.kind === 'shop').map(shop => cell(`shop-${shop.key}`, shopCell(row, shop, openDetails), 'shop-cell')).join('');
    return `<tr class="${resultRowVisible(row) ? '' : 'result-row-filtered'}">${cell('model', escapeHtml(row.model), 'model-cell')}${cell('marketplaces', marketplaceCell(row, openDetails), 'source-cell')}${cell('lowest-stock', offerLink(stockOffer))}${cell('lowest-preorder', offerLink(preorderOffer))}${shopCells}${cell('stock', row.stockQuantity == null ? '—' : `${escapeHtml(row.stockQuantity)} / ${euro(row.stockCost)}`)}${cell('margin', margin == null ? '—' : `${margin >= 0 ? '+' : ''}${margin.toFixed(2)} EUR`)}${cell('status', statusCell(row))}</tr>`;
  }).join('') : `<tr><td colspan="${cols.length}" class="empty">No monitoring results yet.</td></tr>`;
}

function renderActionRequired(run) {
  const shopItems = state.shopResults.filter(item => item.status === 'ACTION_REQUIRED').map(item => ({ ...item, action_kind: 'shops', action_key: item.shop_key, action_name: item.shop_name || item.shop_key }));
  const marketplaceItems = state.tasks.filter(item => item.status === 'ACTION_REQUIRED' && item.assisted).map(item => ({ ...item, model: item.source_model || item.canonical_model, action_kind: 'marketplaces', action_key: item.marketplace_key, action_name: item.marketplace || item.marketplace_key }));
  const items = [...shopItems, ...marketplaceItems];
  state.actionItems = items;
  const review = byId('review-actions');
  review.hidden = items.length === 0;
  review.textContent = items.length ? `Review required checks (${items.length})` : 'Review required checks';
  byId('action-items').innerHTML = items.length ? items.map(item => {
    const link = item.product_url || item.search_url;
    return `<div class="action-item"><div><strong>${escapeHtml(item.model)} · ${escapeHtml(item.action_name)}</strong><span class="muted">${escapeHtml(item.error || 'Browser verification is required before this price can be collected.')}</span></div><div class="action-item-actions">${link ? `<a class="button-link secondary" href="${escapeHtml(link)}" target="_blank" rel="noopener">Open verification</a>` : ''}<button type="button" data-check-action="retry" data-check-kind="${item.action_kind}" data-item-id="${item.item_id}" data-source-key="${escapeHtml(item.action_key)}">Capture again</button><button type="button" class="secondary" data-check-action="not-found" data-check-kind="${item.action_kind}" data-item-id="${item.item_id}" data-source-key="${escapeHtml(item.action_key)}">Mark not found</button><button type="button" class="secondary" data-check-action="manual-price" data-check-kind="${item.action_kind}" data-item-id="${item.item_id}" data-source-key="${escapeHtml(item.action_key)}">Save manual price</button></div></div>`;
  }).join('') : '<p class="muted">No checks currently require browser verification.</p>';

  if (!items.length) {
    state.lastActionSignature = '';
    if (byId('action-dialog').open) byId('action-dialog').close();
    return;
  }
  const signature = items.map(item => `${item.action_kind}:${item.item_id}:${item.action_key}`).sort().join('|');
  if (run.status === 'COMPLETE' && signature !== state.lastActionSignature) {
    state.lastActionSignature = signature;
    if (!byId('action-dialog').open) byId('action-dialog').showModal();
  }
}

async function handleActionDialog(event) {
  const button = event.target.closest('[data-check-action]');
  if (!button || !state.currentRunId) return;
  const action = button.dataset.checkAction;
  let payload = null;
  if (action === 'not-found') {
    if (!window.confirm('Confirm that this model is not available from this source?')) return;
    payload = { status: 'NOT_FOUND' };
  }
  if (action === 'manual-price') {
    const entered = window.prompt('Enter the confirmed in-stock price in EUR:');
    if (entered === null) return;
    const price = Number(entered.trim().replace(',', '.'));
    if (!Number.isFinite(price) || price < 0) {
      showBanner('error', 'Enter a valid non-negative price.');
      return;
    }
    payload = { status: 'SUCCESS', price_eur: price, availability: 'IN_STOCK' };
  }
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = action === 'retry' ? 'Capturing…' : 'Saving…';
  try {
    const base = `/runs/${encodeURIComponent(state.currentRunId)}/${button.dataset.checkKind}/${button.dataset.itemId}/${encodeURIComponent(button.dataset.sourceKey)}`;
    if (action === 'retry') {
      await api(`${base}/retry`, { method: 'POST' });
    } else {
      await api(`${base}/resolve`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    }
    state.lastActionSignature = '';
    showBanner('success', action === 'retry' ? 'The selected check is capturing again.' : 'Manual result saved.');
    await pollRun(state.currentRunId);
    if (action === 'retry') {
      if (state.runPoll) clearInterval(state.runPoll);
      state.runPoll = setInterval(() => pollRun(state.currentRunId), 2000);
    }
  } catch (error) {
    button.disabled = false;
    button.textContent = originalLabel;
    showBanner('error', error.message);
  }
}

function renderRun(run) {
  state.currentRunId = run.id || run.run_id;
  state.tasks = run.tasks || []; state.shopResults = run.shop_results || [];
  const all = [...state.tasks, ...state.shopResults]; const finished = all.filter(item => !['RUNNING', 'PENDING'].includes(item.status)).length;
  const success = all.filter(item => item.status === 'SUCCESS').length; const failed = all.filter(item => ['FAILED', 'INCOMPLETE'].includes(item.status)).length;
  const notFound = all.filter(item => item.status === 'NOT_FOUND').length;
  const actionRequired = all.filter(item => item.status === 'ACTION_REQUIRED').length;
  const cooldown = all.filter(item => item.status === 'COOLDOWN').length;
  const cached = all.filter(item => item.status === 'SUCCESS' && item.cached).length;
  const percent = all.length ? Math.round(finished / all.length * 100) : (run.status === 'COMPLETE' ? 100 : 0);
  byId('progress').hidden = false; byId('progress-fill').style.width = `${percent}%`; byId('progress-text').textContent = `${run.status}: ${finished} of ${all.length} checks (${percent}%)`;
  const actionText = `${actionRequired ? ` · Action required ${actionRequired}` : ''}${cooldown ? ` · Cooldown ${cooldown}` : ''}${cached ? ` · Cached ${cached}` : ''}`;
  const stopped = run.status === 'INCOMPLETE';
  byId('run-state').textContent = run.status === 'RUNNING' ? `Monitoring… Success ${success} · Not found ${notFound} · Failed ${failed}${actionText}` : `${stopped ? 'Stopped' : 'Completed'} · Success ${success} · Not found ${notFound} · Failed ${failed}${actionText}`;
  byId('start-run').disabled = run.status === 'RUNNING'; byId('stop-run').hidden = run.status !== 'RUNNING'; byId('stop-run').disabled = false; renderResults(); renderActionRequired(run);
  if (run.status !== 'RUNNING' && state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; loadExports(); }
}

async function pollRun(runId) { try { renderRun(await api(`/runs/${runId}`)); } catch (error) { if (!state.stopRequested) showBanner('error', error.message); } }
async function startRun() {
  byId('start-run').disabled = true; state.stopRequested = false; state.resultFilterInitialized = false; state.lastActionSignature = ''; Object.values(state.resultFilters).forEach(filter => filter.clear()); Object.values(state.resultFilterKnown).forEach(filter => filter.clear());
  try { const result = await api('/runs', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' }); await pollRun(result.run_id); if (state.runPoll) clearInterval(state.runPoll); state.runPoll = setInterval(() => pollRun(result.run_id), 2000); }
  catch (error) { byId('start-run').disabled = false; showBanner('error', error.message); }
}

async function hardStopRun() {
  if (!state.currentRunId || !window.confirm('Stop the current monitoring run immediately? Completed results will be kept.')) return;
  const button = byId('stop-run'); button.disabled = true; button.textContent = 'Stopping…'; state.stopRequested = true;
  try {
    if (state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; }
    const run = await api(`/runs/${encodeURIComponent(state.currentRunId)}/stop`, { method: 'POST' });
    renderRun(run); showBanner('success', 'Monitoring stopped. You can start a new run.');
  } catch (error) {
    state.stopRequested = false; button.disabled = false; showBanner('error', error.message);
  } finally { button.textContent = '■ Hard stop'; }
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
  byId('action-close').addEventListener('click', () => byId('action-dialog').close()); byId('action-later').addEventListener('click', () => byId('action-dialog').close());
  byId('method-test-close').addEventListener('click', () => byId('method-test-dialog').close()); byId('method-test-cancel').addEventListener('click', () => byId('method-test-dialog').close()); byId('method-test-run').addEventListener('click', runMethodTest);
  byId('review-actions').addEventListener('click', () => { if (!byId('action-dialog').open) byId('action-dialog').showModal(); }); byId('action-items').addEventListener('click', handleActionDialog);
  byId('workbook-upload').addEventListener('click', () => upload('workbook')); byId('stock-upload').addEventListener('click', () => upload('stock')); byId('start-run').addEventListener('click', startRun); byId('stop-run').addEventListener('click', hardStopRun);
  byId('marketplace-master').addEventListener('change', event => updateMaster('marketplace', event.target.checked)); byId('shop-master').addEventListener('change', event => updateMaster('shop', event.target.checked));
  for (const kind of ['source', 'stock']) { let timer; byId(`${kind}-search`).addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => loadKind(kind).catch(error => showBanner('error', error.message)), 220); }); }
}

async function initialize() {
  wireEvents();
  try {
    const [health] = await Promise.all([api('/health'), loadSources()]); byId('service-state').textContent = `v${health.version} · monitoring service ${health.legacy_service}`; byId('service-state').classList.add('ok');
    const policy = health.polite_monitoring; if (policy) byId('polite-mode-state').textContent = `Polite mode · 1 request per shop · ${policy.delay_seconds[0]}–${policy.delay_seconds[1]} s pacing · ${Math.round(policy.cache_ttl_seconds / 3600)} h cache · ${Math.round(policy.cooldown_seconds / 60)} min protection cooldown`;
    await Promise.all([loadCatalog(), loadSetupStatus(), loadExports(), loadLogs(), loadBrowserBridge()]); try { renderRun(await api('/runs/latest')); } catch { renderResults(); }
    setInterval(loadLogs, 10000); setInterval(loadBrowserBridge, 5000);
  } catch (error) { byId('service-state').textContent = 'Startup error'; showBanner('error', error.message); }
}

initialize();
