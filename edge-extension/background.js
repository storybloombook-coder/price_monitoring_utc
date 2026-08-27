const DEFAULT_APP_URL = 'http://127.0.0.1:8000';
const POLL_ALARM = 'price-monitor-poll';
let polling = false;

const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function settings() {
  const saved = await chrome.storage.local.get({ appUrl: DEFAULT_APP_URL, closeSuccessfulTabs: true });
  return { ...saved, appUrl: String(saved.appUrl || DEFAULT_APP_URL).replace(/\/$/, '') };
}

async function setStatus(status, message, extra = {}) {
  await chrome.storage.local.set({ bridgeStatus: { status, message, updatedAt: Date.now(), ...extra } });
  const badge = status === 'working' ? '…' : status === 'attention' ? '!' : status === 'connected' ? '✓' : '';
  await chrome.action.setBadgeText({ text: badge });
  await chrome.action.setBadgeBackgroundColor({ color: status === 'attention' ? '#a66105' : '#146c43' });
}

async function bridgeFetch(path, options = {}) {
  const { appUrl } = await settings();
  return fetch(`${appUrl}${path}`, { cache: 'no-store', ...options });
}

function waitForTabComplete(tabId, timeoutMilliseconds = 45000) {
  return new Promise(async (resolve, reject) => {
    let settled = false;
    const finish = error => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      error ? reject(error) : resolve();
    };
    const listener = (updatedId, changeInfo) => {
      if (updatedId === tabId && changeInfo.status === 'complete') finish();
    };
    const timer = setTimeout(() => finish(new Error('The retailer page did not finish loading')), timeoutMilliseconds);
    chrome.tabs.onUpdated.addListener(listener);
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab.status === 'complete') finish();
    } catch (error) {
      finish(error);
    }
  });
}

function extractRenderedPage(model) {
  const bodyText = String(document.body?.innerText || '').slice(0, 750000);
  const lowered = `${document.title} ${bodyText}`.toLowerCase();
  const challengeTokens = [
    'performing security verification', 'just a moment...', 'verify you are human',
    'attention required!', 'sorry, you have been blocked', 'cf-chl-'
  ];
  const securityChallenge = challengeTokens.some(token => lowered.includes(token)) || Boolean(
    document.querySelector('[class*="cf-chl"], #challenge-running, iframe[src*="challenges.cloudflare.com"]')
  );
  const expected = String(model || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const metadata = [...document.querySelectorAll('meta, script[type="application/ld+json"]')]
    .map(element => element.outerHTML)
    .join('\n');
  const links = [...document.querySelectorAll('a[href]')]
    .filter(anchor => {
      if (!expected) return false;
      const value = `${anchor.textContent || ''} ${anchor.href || ''}`.toLowerCase().replace(/[^a-z0-9]/g, '');
      return value.includes(expected);
    })
    .slice(0, 400)
    .map(anchor => `<a href="${anchor.href.replaceAll('&', '&amp;').replaceAll('"', '&quot;')}">${String(anchor.textContent || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')}</a>`)
    .join('\n');
  const escapedText = bodyText.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  const incomplete = Boolean(document.querySelector('[class*="MuiSkeleton"]')) && !links;
  return {
    url: location.href,
    title: document.title,
    html: `<html><head>${metadata}</head><body>${links}<pre>${escapedText}</pre></body></html>`,
    security_challenge: securityChallenge,
    incomplete
  };
}

async function snapshot(tabId, model) {
  const result = await chrome.scripting.executeScript({
    target: { tabId },
    func: extractRenderedPage,
    args: [model]
  });
  if (!result?.[0]?.result) throw new Error('The extension could not read the retailer page');
  return result[0].result;
}

async function submit(jobId, payload) {
  const response = await bridgeFetch(`/browser-bridge/jobs/${encodeURIComponent(jobId)}/result`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!response.ok && response.status !== 404) throw new Error(`PriceMonitor rejected the browser result (${response.status})`);
}

async function processJob(job) {
  await setStatus('working', `Opening ${job.shop_key} for ${job.model}`, { job });
  let tab;
  let captured;
  try {
    tab = await chrome.tabs.create({ url: job.url, active: true });
    await waitForTabComplete(tab.id);
    const deadline = Date.now() + 140000;
    const incompleteDeadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      await delay(3500);
      captured = await snapshot(tab.id, job.model);
      if (captured.security_challenge) {
        await setStatus('attention', `Complete the visible ${job.shop_key} security check`, { job });
        continue;
      }
      if (captured.incomplete && Date.now() < incompleteDeadline) continue;
      break;
    }
    if (!captured || captured.security_challenge) {
      captured = {
        url: tab.url || job.url,
        html: '',
        security_challenge: true,
        error: 'Visible browser verification was not completed in time'
      };
    }
    await submit(job.id, captured);
    if (!captured.security_challenge) {
      const { closeSuccessfulTabs } = await settings();
      if (closeSuccessfulTabs) await chrome.tabs.remove(tab.id).catch(() => {});
      await setStatus('connected', `Captured ${job.shop_key} for ${job.model}`);
    }
  } catch (error) {
    await submit(job.id, {
      url: tab?.url || job.url,
      html: '',
      security_challenge: true,
      error: String(error?.message || error)
    }).catch(() => {});
    await setStatus('attention', String(error?.message || error), { job });
  }
}

async function pollOnce() {
  const response = await bridgeFetch('/browser-bridge/jobs/next?wait_seconds=25');
  if (response.status === 204) {
    await setStatus('connected', 'Connected to PriceMonitor');
    return;
  }
  if (!response.ok) throw new Error(`PriceMonitor connection failed (${response.status})`);
  await processJob(await response.json());
}

async function pollLoop() {
  if (polling) return;
  polling = true;
  try {
    for (let attempt = 0; attempt < 4; attempt += 1) await pollOnce();
  } catch (error) {
    await setStatus('disconnected', String(error?.message || error));
  } finally {
    polling = false;
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
  void pollLoop();
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
  void pollLoop();
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === POLL_ALARM) void pollLoop();
});
chrome.storage.onChanged.addListener(changes => {
  if (changes.appUrl) void pollLoop();
});
void chrome.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
void pollLoop();
