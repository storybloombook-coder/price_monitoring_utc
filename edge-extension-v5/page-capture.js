// Deliberate active-tab capture, independent of timed background monitoring jobs.
let captureWork = Promise.resolve();
function serializeCapture(work) {
  const next = captureWork.then(work, work);
  captureWork = next.catch(() => {});
  return next;
}
async function captureQueue() {
  return (await chrome.storage.local.get({ pageCaptures: [] })).pageCaptures;
}
async function saveCaptureQueue(queue) {
  if (new TextEncoder().encode(JSON.stringify(queue)).length > 7_500_000) throw new Error('Capture queue is full. Save or discard older pages first.');
  await chrome.storage.local.set({ pageCaptures: queue });
}
function captureAppUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(url.hostname) || !url.port || url.username || url.password) throw new Error('Use the local PriceMonitor address');
  return url.origin;
}
function salidziniPage(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || !['salidzini.lv', 'www.salidzini.lv'].includes(url.hostname) ||
      (url.port && url.port !== '443') || url.username || url.password || url.pathname.replace(/\/$/, '') !== '/cena') {
    throw new Error('Open Salidzini search results in the active tab first');
  }
  return url.href;
}
async function captureRequest(record, path, payload) {
  const current = captureAppUrl((await settings()).appUrl);
  if (current !== record.appUrl) throw new Error('The app address changed. Restore the original address or discard this capture.');
  const response = await fetch(record.appUrl + path, {
    method: 'POST', cache: 'no-store', signal: AbortSignal.timeout(8000),
    headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload)
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.detail || `PriceMonitor rejected capture (${response.status})`);
    error.httpStatus = response.status;
    throw error;
  }
  return body;
}
async function flushPageCaptures() {
  const queue = await captureQueue();
  for (const record of [...queue]) {
    if (!['queued', 'applying'].includes(record.state)) continue;
    try {
      if (record.state === 'applying') {
        const result = await captureRequest(record, '/browser-bridge/page-apply', record.applyPayload);
        queue.splice(queue.indexOf(record), 1);
        await chrome.storage.local.set({ lastPageCapture: { ...result, saved_at: new Date().toISOString() } });
      } else {
        record.preview = await captureRequest(record, '/browser-bridge/page-preview', record.payload);
        record.state = 'preview';
        record.selected = record.preview.offers.map((_, i) => i);
        record.complete = false;
      }
      record.error = '';
    } catch (error) {
      record.error = String(error.message || error);
      if (error.httpStatus && error.httpStatus < 500) record.state = 'error';
      // Network failure retains both the snapshot and a previously confirmed save.
    }
    await saveCaptureQueue(queue);
  }
  return queue;
}
async function queueActivePage(message) {
  const tab = await chrome.tabs.get(message.tabId);
  const url = salidziniPage(tab.url);
  const model = String(message.model || '').trim().toUpperCase();
  if (!model || model.length > 100) throw new Error('Enter the original monitoring SKU');
  const captured = await snapshot(tab.id, model);
  salidziniPage(captured.url);
  if (captured.url !== url) throw new Error('The page changed while capturing. Try again.');
  if (captured.security_challenge) throw new Error('Complete the CAPTCHA first, then click Send to PriceMonitor. There is no time limit.');
  if (new TextEncoder().encode(captured.html).length > 2_000_000) throw new Error('This page is too large to capture (2 MB maximum).');
  const queue = await captureQueue();
  if (queue.length >= 5) throw new Error('Save or discard a queued page first (maximum 5 pages).');
  const record = { capture_id: crypto.randomUUID(), appUrl: captureAppUrl((await settings()).appUrl), state: 'queued',
    payload: { ...captured, model, captured_at: new Date().toISOString() } };
  queue.push(record);
  await saveCaptureQueue(queue); // Durable before attempting any local connection.
  await flushPageCaptures();
  return { capture_id: record.capture_id };
}
async function handlePageCapture(message) {
  if (message.type === 'capture-current') return queueActivePage(message);
  const queue = await captureQueue();
  const record = queue.find(r => r.capture_id === message.capture_id);
  if (!record) throw new Error('This capture was already saved or discarded');
  if (message.type === 'capture-discard') {
    await saveCaptureQueue(queue.filter(r => r !== record));
    return {};
  }
  if (message.type === 'capture-refresh') {
    // Explicit refresh permits rebinding a still-unapplied snapshot to a new run.
    if (record.state === 'applying') throw new Error('A confirmed save is pending. Wait for its receipt before refreshing.');
    record.state = 'queued'; record.preview = null; record.error = '';
    await saveCaptureQueue(queue);
    await flushPageCaptures();
    return {};
  }
  if (message.type === 'capture-selection') {
    if (record.state !== 'preview') throw new Error('Refresh the preview first');
    record.selected = message.selected; record.complete = message.complete === true;
    await saveCaptureQueue(queue);
    return {};
  }
  if (message.type === 'capture-apply') {
    if (record.state !== 'preview') throw new Error('Refresh the preview first');
    record.applyPayload = { ...record.payload, capture_id: record.capture_id,
      run_id: record.preview.run_id, item_id: record.preview.item_id,
      expected_signature: record.preview.expected_signature,
      selected_indices: message.selected, all_pages_reviewed: message.complete === true };
    record.state = 'applying'; record.error = '';
    await saveCaptureQueue(queue);
    await flushPageCaptures();
    return {};
  }
  throw new Error('Unknown capture action');
}
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message?.type?.startsWith('capture-')) return false;
  if (sender.id !== chrome.runtime.id) return false;
  serializeCapture(() => handlePageCapture(message))
    .then(result => sendResponse({ ok: true, ...result }))
    .catch(error => sendResponse({ ok: false, error: String(error.message || error) }));
  return true;
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === POLL_ALARM) void serializeCapture(flushPageCaptures).catch(() => {});
});
void serializeCapture(flushPageCaptures).catch(() => {});
