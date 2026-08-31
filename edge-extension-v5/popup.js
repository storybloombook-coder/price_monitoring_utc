const DEFAULT_APP_URL = 'http://127.0.0.1:8050';
const statusElement = document.getElementById('status');
const urlInput = document.getElementById('app-url');
const closeTabsInput = document.getElementById('close-tabs');

function showStatus(status, message) {
  statusElement.className = `status ${status || ''}`;
  statusElement.textContent = message;
}

function validLocalUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname) && url.port;
  } catch {
    return false;
  }
}

async function refresh() {
  const saved = await chrome.storage.local.get({
    appUrl: DEFAULT_APP_URL,
    closeSuccessfulTabs: true,
    bridgeStatus: null
  });
  if (document.activeElement !== urlInput) urlInput.value = saved.appUrl;
  if (document.activeElement !== closeTabsInput) closeTabsInput.checked = saved.closeSuccessfulTabs;
  try {
    const response = await fetch(`${String(saved.appUrl).replace(/\/$/, '')}/browser-bridge/status`, {
      cache: 'no-store'
    });
    if (!response.ok) throw new Error(`PriceMonitor connection failed (${response.status})`);
    const live = await response.json();
    const transport = live.transport === 'websocket' ? 'live channel' : live.transport === 'polling' ? 'recovery polling' : 'offline';
    showStatus(live.connected ? 'connected' : 'disconnected', live.connected
      ? `Connected to PriceMonitor · ${transport}`
      : 'PriceMonitor is reachable. Manual page capture is available; the background channel is offline.');
  } catch (error) {
    showStatus('disconnected', `PriceMonitor is unavailable: ${String(error?.message || error)}`);
  }
}

document.getElementById('save').addEventListener('click', async () => {
  const appUrl = urlInput.value.trim().replace(/\/$/, '');
  if (!validLocalUrl(appUrl)) {
    showStatus('attention', 'Use a local address such as http://127.0.0.1:8050');
    return;
  }
  await chrome.storage.local.set({ appUrl, closeSuccessfulTabs: closeTabsInput.checked });
  showStatus('', 'Connecting…');
  try {
    const response = await chrome.runtime.sendMessage({ type: 'connect' });
    if (!response?.ok) throw new Error(response?.error || 'Connection failed');
    showStatus('connected', 'Connected to PriceMonitor');
    await chrome.storage.local.set({ bridgeStatus: { status: 'connected', message: 'Connected to PriceMonitor', updatedAt: Date.now() } });
  } catch (error) {
    showStatus('disconnected', String(error?.message || error));
  }
});

void refresh();
window.setInterval(refresh, 2000);
