const byId = id => document.getElementById(id);
const state = { source: [], sourceOptions: [], stock: [], summary: null, tasks: [], runPoll: null };

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data?.detail || data || `Ошибка ${response.status}`);
  return data;
}

function showBanner(kind, message) {
  const error = byId('error-banner');
  const success = byId('success-banner');
  error.hidden = true;
  success.hidden = true;
  if (!message) return;
  const target = kind === 'error' ? error : success;
  target.textContent = message;
  target.hidden = false;
  window.setTimeout(() => { target.hidden = true; }, 5000);
}

function badge(label, type) {
  return `<span class="badge ${escapeHtml(type)}">${escapeHtml(label)}</span>`;
}

function itemStatus(item) {
  if (item.state === 'trash') return badge('Корзина', 'trash');
  if (item.paused) return badge('Пауза', 'paused');
  return badge('Активно', 'active');
}

function actionButtons(item) {
  if (item.state === 'trash') {
    return `<button class="link-action" data-action="restore" data-id="${item.id}">Восстановить</button>`;
  }
  return `
    <button class="link-action" data-action="edit" data-id="${item.id}">Изменить</button>
    <button class="link-action" data-action="pause" data-id="${item.id}">${item.paused ? 'Возобновить' : 'Пауза'}</button>
    <button class="link-action danger" data-action="trash" data-id="${item.id}">В корзину</button>`;
}

function renderSource() {
  const tbody = byId('source-rows');
  tbody.innerHTML = state.source.length ? state.source.map(item => `
    <tr>
      <td><span class="item-primary">${escapeHtml(item.model)}</span><span class="item-secondary">${escapeHtml(item.origin)}</span></td>
      <td>${escapeHtml((item.source_sheets || []).join(', ') || 'TV')}</td>
      <td>${itemStatus(item)}</td>
      <td>${actionButtons(item)}</td>
    </tr>`).join('') : '<tr><td colspan="4" class="empty">Позиции не найдены.</td></tr>';
}

function renderStock() {
  const tbody = byId('stock-rows');
  tbody.innerHTML = state.stock.length ? state.stock.map(item => `
    <tr>
      <td>
        <span class="item-primary">${escapeHtml(item.nomenclature)}</span>
        <span class="item-secondary">${item.model ? escapeHtml(item.model) : 'Модель не указана'} · ${escapeHtml(item.warehouse || 'Склад не указан')}</span>
      </td>
      <td>${Number(item.quantity || 0).toLocaleString('ru-RU')} шт.<span class="item-secondary">${Number(item.unit_cost_eur || 0).toFixed(2)} EUR</span></td>
      <td>${itemStatus(item)} ${item.state !== 'trash' && !item.matched ? badge('Нет связи', 'unmatched') : ''}</td>
      <td>${actionButtons(item)}</td>
    </tr>`).join('') : '<tr><td colspan="4" class="empty">Позиции не найдены.</td></tr>';
}

function renderSummary() {
  if (!state.summary) return;
  const s = state.summary.source;
  const w = state.summary.stock;
  byId('catalog-summary').textContent = `Source: ${s.active} активных, ${s.paused} на паузе · Stock: ${w.active} активных, ${w.unmatched} без связи`;
  byId('source-model-options').innerHTML = state.sourceOptions
    .filter(item => item.state !== 'trash')
    .map(item => `<option value="${escapeHtml(item.model)}"></option>`).join('');
}

async function loadKind(kind) {
  const scope = byId(`${kind}-scope`).value;
  const query = byId(`${kind}-search`).value.trim();
  state[kind] = await api(`/catalog/items?kind=${kind}&scope=${scope}&q=${encodeURIComponent(query)}`);
  if (kind === 'source') renderSource(); else renderStock();
}

async function loadCatalog() {
  const [summary, sourceOptions] = await Promise.all([
    api('/catalog/summary'),
    api('/catalog/items?kind=source&scope=active'),
    loadKind('source'),
    loadKind('stock')
  ]);
  state.summary = summary;
  state.sourceOptions = sourceOptions;
  renderSummary();
}

function findItem(id) {
  return [...state.source, ...state.stock].find(item => item.id === Number(id));
}

function openEditor(kind, item = null) {
  byId('item-form').reset();
  byId('item-kind').value = kind;
  byId('item-id').value = item?.id || '';
  byId('dialog-kind').textContent = kind.toUpperCase();
  byId('dialog-title').textContent = item ? 'Редактировать позицию' : 'Новая позиция';
  byId('source-fields').hidden = kind !== 'source';
  byId('stock-fields').hidden = kind !== 'stock';
  byId('item-paused').checked = Boolean(item?.paused);
  if (kind === 'source') {
    byId('source-model').value = item?.model || '';
    const sheets = item?.source_sheets || ['TV'];
    document.querySelectorAll('[name="source-sheet"]').forEach(input => { input.checked = sheets.includes(input.value); });
  } else {
    byId('stock-name').value = item?.nomenclature || '';
    byId('stock-model').value = item?.model || '';
    byId('stock-warehouse').value = item?.warehouse || '';
    byId('stock-quantity').value = item?.quantity ?? 0;
    byId('stock-cost').value = item?.unit_cost_eur ?? 0;
  }
  byId('item-dialog').showModal();
}

async function saveItem(event) {
  event.preventDefault();
  const kind = byId('item-kind').value;
  const id = byId('item-id').value;
  const payload = kind === 'source' ? {
    model: byId('source-model').value,
    source_sheets: [...document.querySelectorAll('[name="source-sheet"]:checked')].map(input => input.value),
    paused: byId('item-paused').checked
  } : {
    nomenclature: byId('stock-name').value,
    model: byId('stock-model').value,
    warehouse: byId('stock-warehouse').value,
    quantity: Number(byId('stock-quantity').value || 0),
    unit_cost_eur: Number(byId('stock-cost').value || 0),
    paused: byId('item-paused').checked
  };
  try {
    await api(id ? `/catalog/items/${id}` : `/catalog/items/${kind}`, {
      method: id ? 'PATCH' : 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload)
    });
    byId('item-dialog').close();
    await loadCatalog();
    await loadSetupStatus();
    showBanner('success', id ? 'Позиция обновлена.' : 'Позиция добавлена.');
  } catch (error) {
    showBanner('error', error.message);
  }
}

async function handleItemAction(event) {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const item = findItem(button.dataset.id);
  if (!item) return;
  try {
    if (button.dataset.action === 'edit') return openEditor(item.kind, item);
    if (button.dataset.action === 'pause') {
      await api(`/catalog/items/${item.id}`, {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ paused: !item.paused })
      });
    }
    if (button.dataset.action === 'trash') await api(`/catalog/items/${item.id}`, { method: 'DELETE' });
    if (button.dataset.action === 'restore') await api(`/catalog/items/${item.id}/restore`, { method: 'POST' });
    await loadCatalog();
    await loadSetupStatus();
  } catch (error) {
    showBanner('error', error.message);
  }
}

async function upload(kind) {
  const input = byId(kind === 'workbook' ? 'workbook-file' : 'stock-file');
  const button = byId(kind === 'workbook' ? 'workbook-upload' : 'stock-upload');
  if (!input.files[0]) return showBanner('error', 'Сначала выберите Excel-файл.');
  const form = new FormData();
  form.append('file', input.files[0]);
  button.disabled = true;
  try {
    const result = await api(kind === 'workbook' ? '/workbook/upload' : '/stock/upload', { method: 'POST', body: form });
    input.value = '';
    await Promise.all([loadCatalog(), loadSetupStatus()]);
    const count = result.models_found ?? result.imported;
    showBanner('success', `Файл распознан: ${count} позиций.`);
  } catch (error) {
    showBanner('error', error.message);
  } finally {
    button.disabled = false;
  }
}

async function loadSetupStatus() {
  const [workbook, stock] = await Promise.all([api('/workbook'), api('/stock')]);
  byId('workbook-status').textContent = `${workbook.models_found} моделей в каталоге · ${workbook.source_workbook}`;
  byId('stock-status').textContent = `${stock.count} позиций · ${stock.matched} связаны с моделями`;
}

function offerCell(offer) {
  if (!offer) return '—';
  const label = `${escapeHtml(offer.price_eur)} EUR · ${escapeHtml(offer.store)}`;
  return offer.url ? `<a href="${escapeHtml(offer.url)}" target="_blank" rel="noopener">${label}</a>` : label;
}

function renderResults(tasks) {
  state.tasks = tasks || [];
  byId('result-rows').innerHTML = state.tasks.length ? state.tasks.map(task => {
    const statusType = task.status.toLowerCase().replace('_', '-');
    const margin = task.stock_margin_eur == null ? '—' : `${task.stock_margin_eur >= 0 ? '+' : ''}${Number(task.stock_margin_eur).toFixed(2)} EUR`;
    return `<tr>
      <td>${escapeHtml(task.source_model || task.canonical_model)}</td>
      <td>${escapeHtml(task.marketplace)}</td>
      <td>${badge(task.status, statusType)}</td>
      <td>${escapeHtml(task.matched_title || '—')}</td>
      <td>${offerCell(task.cheapest_in_stock)}</td>
      <td>${task.stock_quantity == null ? '—' : `${task.stock_quantity} / ${Number(task.stock_unit_cost_eur || 0).toFixed(2)} EUR`}</td>
      <td>${margin}</td>
    </tr>`;
  }).join('') : '<tr><td colspan="7" class="empty">В этом запуске нет задач.</td></tr>';
}

function renderRun(run) {
  const tasks = run.tasks || [];
  const finished = tasks.filter(task => ['SUCCESS', 'NOT_FOUND', 'INCOMPLETE', 'FAILED'].includes(task.status)).length;
  const percent = tasks.length ? Math.round(finished / tasks.length * 100) : (run.status === 'COMPLETE' ? 100 : 0);
  byId('progress').hidden = false;
  byId('progress-fill').style.width = `${percent}%`;
  byId('progress-text').textContent = `${run.status}: ${finished} из ${tasks.length} задач (${percent}%)`;
  byId('run-state').textContent = run.status === 'RUNNING' ? 'Проверка выполняется…' : 'Последний запуск завершён.';
  byId('start-run').disabled = run.status === 'RUNNING';
  renderResults(tasks);
  if (run.status !== 'RUNNING' && state.runPoll) {
    clearInterval(state.runPoll);
    state.runPoll = null;
    loadExports();
  }
}

async function pollRun(runId) {
  try { renderRun(await api(`/runs/${runId}`)); }
  catch (error) { showBanner('error', error.message); }
}

async function startRun() {
  byId('start-run').disabled = true;
  try {
    const result = await api('/runs', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
    await pollRun(result.run_id);
    if (state.runPoll) clearInterval(state.runPoll);
    state.runPoll = setInterval(() => pollRun(result.run_id), 2000);
  } catch (error) {
    byId('start-run').disabled = false;
    showBanner('error', error.message);
  }
}

async function loadExports() {
  try {
    const items = await api('/exports?limit=6');
    byId('exports').innerHTML = items.length ? items.map(item =>
      `<div class="export-line"><a href="/exports/file/${encodeURIComponent(item.filename)}">${escapeHtml(item.filename)}</a> · ${Math.round(item.size_bytes / 1024)} KB</div>`
    ).join('') : 'Экспортов пока нет.';
  } catch { byId('exports').textContent = 'Экспорты недоступны.'; }
}

async function loadLogs() {
  try {
    const items = await api('/logs?limit=8');
    byId('logs').innerHTML = items.length ? items.map(item =>
      `<div class="log-line">[${escapeHtml(item.level)}] ${escapeHtml(item.message)}</div>`
    ).join('') : 'Записей пока нет.';
  } catch { byId('logs').textContent = 'Журнал недоступен.'; }
}

function wireEvents() {
  document.querySelectorAll('[data-add]').forEach(button => button.addEventListener('click', () => openEditor(button.dataset.add)));
  byId('source-rows').addEventListener('click', handleItemAction);
  byId('stock-rows').addEventListener('click', handleItemAction);
  byId('item-form').addEventListener('submit', saveItem);
  byId('dialog-close').addEventListener('click', () => byId('item-dialog').close());
  byId('dialog-cancel').addEventListener('click', () => byId('item-dialog').close());
  byId('workbook-upload').addEventListener('click', () => upload('workbook'));
  byId('stock-upload').addEventListener('click', () => upload('stock'));
  byId('start-run').addEventListener('click', startRun);
  for (const kind of ['source', 'stock']) {
    byId(`${kind}-scope`).addEventListener('change', () => loadKind(kind).catch(error => showBanner('error', error.message)));
    let timer;
    byId(`${kind}-search`).addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => loadKind(kind).catch(error => showBanner('error', error.message)), 220);
    });
  }
}

async function initialize() {
  wireEvents();
  try {
    const [health, marketplaces] = await Promise.all([api('/health'), api('/marketplaces')]);
    byId('service-state').textContent = `v${health.version} · сервис мониторинга ${health.legacy_service}`;
    byId('service-state').classList.add('ok');
    byId('marketplaces').innerHTML = marketplaces.map(item => badge(`${item.name}: ${item.status}`, item.status === 'LIVE' ? 'active' : 'paused')).join('');
    await Promise.all([loadCatalog(), loadSetupStatus(), loadExports(), loadLogs()]);
    try { renderRun(await api('/runs/latest')); } catch { /* first launch */ }
    setInterval(loadLogs, 10000);
  } catch (error) {
    byId('service-state').textContent = 'Ошибка запуска';
    showBanner('error', error.message);
  }
}

initialize();
