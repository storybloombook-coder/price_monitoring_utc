const DEFAULT_APP_URL = 'http://127.0.0.1:8000';
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
  urlInput.value = saved.appUrl;
  closeTabsInput.checked = saved.closeSuccessfulTabs;
  const state = saved.bridgeStatus;
  showStatus(state?.status || 'disconnected', state?.message || 'Start PriceMonitor, then connect.');
}

document.getElementById('save').addEventListener('click', async () => {
  const appUrl = urlInput.value.trim().replace(/\/$/, '');
  if (!validLocalUrl(appUrl)) {
    showStatus('attention', 'Use a local address such as http://127.0.0.1:8000');
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
