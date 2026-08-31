const captureMessage = document.getElementById('capture-message');
const captureList = document.getElementById('capture-queue');
const captureButton = document.getElementById('capture-current');
const captureModel = document.getElementById('capture-model');
let captureTabId;
const htmlEscape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
async function sendCapture(message) {
  const reply = await chrome.runtime.sendMessage(message);
  if (!reply?.ok) throw new Error(reply?.error || 'Extension did not respond. Reopen its popup.');
  return reply;
}
function selectedOffers(container) {
  return [...container.querySelectorAll('[data-offer-index]:checked')].map(el => Number(el.dataset.offerIndex));
}
async function renderCaptures() {
  const { pageCaptures = [], lastPageCapture } = await chrome.storage.local.get(['pageCaptures', 'lastPageCapture']);
  captureList.innerHTML = pageCaptures.map(record => {
    const p = record.preview;
    const ready = record.state === 'preview';
    const offers = ready ? p.offers.map((o, i) => `<label class="offer-row"><input type="checkbox" data-offer-index="${i}" ${(record.selected || []).includes(i) ? 'checked' : ''}><span><b>${htmlEscape(o.store)} · ${Number(o.price_eur).toFixed(2)} EUR</b><small>${htmlEscape(o.title)}</small><small>${htmlEscape(o.availability.replaceAll('_', ' '))}</small></span></label>`).join('') : '';
    return `<section class="capture-record" data-capture-id="${htmlEscape(record.capture_id)}"><h3>${htmlEscape(record.payload.model)} · ${htmlEscape(record.state)}</h3>
      <small>Captured ${htmlEscape(new Date(record.payload.captured_at).toLocaleString())}</small>
      ${record.error ? `<p class="capture-error">${htmlEscape(record.error)}</p>` : ''}
      ${ready ? `<p>Review ${p.offers.length} offers. Saving replaces this page's previous prices, not the other pages.</p><small>Run: ${htmlEscape(p.run_id)}</small><div class="capture-offers">${offers}</div>
      <p>${p.next_pages.length ? `${p.next_pages.length} later page link(s): save this page as partial, open the next page and send it too.` : 'Only this captured page was read. Mark complete only after checking every page.'}</p>
      <label class="check"><input type="checkbox" data-all-pages ${record.complete ? 'checked' : ''} ${p.next_pages.length || p.rejected || p.incomplete ? 'disabled' : ''}>All pages and offers for this SKU reviewed</label>
      <button data-capture-action="apply">Save selected prices</button>` : `<p>${record.state === 'applying' ? 'Your confirmed save is queued; it will retry when the app is reachable.' : record.state === 'queued' ? 'Page saved locally. Waiting for PriceMonitor; no prices have been applied.' : 'Nothing applied. Refresh the preview after resolving the message above.'}</p>`}
      <div class="capture-actions"><button class="secondary" data-capture-action="refresh" ${record.state === 'applying' ? 'disabled' : ''}>Refresh preview</button><button class="secondary" data-capture-action="discard">Discard snapshot</button></div></section>`;
  }).join('');
  if (!pageCaptures.length && lastPageCapture) {
    captureList.textContent = `${lastPageCapture.model}: ${lastPageCapture.saved} offers saved · ${new Date(lastPageCapture.saved_at).toLocaleString()}. The PriceMonitor table refreshes automatically.`;
  }
}
captureButton.addEventListener('click', async () => {
  captureButton.disabled = true;
  captureMessage.textContent = 'Reading this tab…';
  try {
    await sendCapture({ type: 'capture-current', tabId: captureTabId, model: captureModel.value });
    captureMessage.textContent = 'Page captured. Review the preview below; if offline, it remains queued locally.';
  } catch (error) { captureMessage.textContent = error.message; }
  finally { captureButton.disabled = false; await renderCaptures(); }
});
captureList.addEventListener('click', async event => {
  const button = event.target.closest('[data-capture-action]');
  if (!button) return;
  const container = button.closest('[data-capture-id]');
  button.disabled = true;
  try {
    await sendCapture({ type: `capture-${button.dataset.captureAction}`, capture_id: container.dataset.captureId,
      selected: selectedOffers(container), complete: container.querySelector('[data-all-pages]')?.checked === true });
    captureMessage.textContent = '';
  } catch (error) { captureMessage.textContent = error.message; }
  finally { await renderCaptures(); }
});
captureList.addEventListener('change', event => {
  const container = event.target.closest('[data-capture-id]');
  if (container) void sendCapture({ type: 'capture-selection', capture_id: container.dataset.captureId,
    selected: selectedOffers(container), complete: container.querySelector('[data-all-pages]')?.checked === true }).catch(error => { captureMessage.textContent = error.message; });
});
chrome.storage.onChanged.addListener(changes => {
  if (changes.pageCaptures || changes.lastPageCapture) void renderCaptures();
});
void (async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  captureTabId = tab?.id;
  try {
    const url = new URL(tab?.url);
    if (['salidzini.lv', 'www.salidzini.lv'].includes(url.hostname)) captureModel.value = (url.searchParams.get('q') || '').replace(/^TCL[\s_-]*/i, '').toUpperCase();
  } catch { /* A restricted tab has no readable URL. */ }
  await renderCaptures();
})();
