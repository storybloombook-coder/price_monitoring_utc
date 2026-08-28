const DEFAULT_APP_URL = 'http://127.0.0.1:8000';
const POLL_ALARM = 'price-monitor-poll';
const MAX_ACTIVE_JOBS = 1;
const JOB_TIMEOUT_MS = 45000;
const JOB_ALARM_PREFIX = 'price-monitor-job:';
const SOCKET_HEARTBEAT_MS = 20000;
const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000];
let polling = false;
const inspecting = new Set();
let bridgeSocket = null;
let socketHeartbeat = null;
let reconnectTimer = null;
let reconnectAttempt = 0;

async function settings() {
  const saved = await chrome.storage.local.get({ appUrl: DEFAULT_APP_URL, closeSuccessfulTabs: true });
  return { ...saved, appUrl: String(saved.appUrl || DEFAULT_APP_URL).replace(/\/$/, '') };
}

async function activeJobs() {
  return (await chrome.storage.local.get({ activeJobs: {} })).activeJobs || {};
}

async function saveActiveJobs(jobs) {
  await chrome.storage.local.set({ activeJobs: jobs });
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

function socketUrl(appUrl) {
  const url = new URL(appUrl);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = '/browser-bridge/ws';
  url.search = '';
  url.hash = '';
  return url.toString();
}

function socketOpen() {
  return bridgeSocket?.readyState === WebSocket.OPEN;
}

function sendSocket(message) {
  if (!socketOpen()) return false;
  bridgeSocket.send(JSON.stringify(message));
  return true;
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  const delay = RECONNECT_DELAYS_MS[Math.min(reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)];
  reconnectAttempt += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void connectWebSocket();
  }, delay);
}

async function connectWebSocket() {
  if (bridgeSocket?.readyState === WebSocket.OPEN || bridgeSocket?.readyState === WebSocket.CONNECTING) return;
  const { appUrl } = await settings();
  const socket = new WebSocket(socketUrl(appUrl));
  bridgeSocket = socket;
  socket.onopen = async () => {
    reconnectAttempt = 0;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    if (socketHeartbeat) clearInterval(socketHeartbeat);
    socketHeartbeat = setInterval(() => sendSocket({ type: 'heartbeat', at: Date.now() }), SOCKET_HEARTBEAT_MS);
    const jobs = await activeJobs();
    sendSocket({ type: 'hello', active_job_ids: Object.keys(jobs) });
    await setStatus('connected', 'Connected to PriceMonitor · live channel');
    await resumeJobs().catch(() => {});
  };
  socket.onmessage = event => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === 'ping') {
      sendSocket({ type: 'heartbeat', at: Date.now() });
      return;
    }
    if (message.type === 'job' && message.job) {
      void activeJobs().then(jobs => {
        if (jobs[message.job.id]) return inspectJob(message.job.id);
        if (Object.keys(jobs).length >= MAX_ACTIVE_JOBS) return;
        void acceptJob(message.job);
      });
    }
  };
  socket.onerror = () => socket.close();
  socket.onclose = () => {
    if (bridgeSocket === socket) bridgeSocket = null;
    if (socketHeartbeat) clearInterval(socketHeartbeat);
    socketHeartbeat = null;
    void setStatus('reconnecting', 'Reconnecting to PriceMonitor…');
    scheduleReconnect();
  };
}

async function heartbeat() {
  const response = await bridgeFetch('/browser-bridge/heartbeat', { method: 'POST' });
  if (!response.ok) throw new Error(`PriceMonitor connection failed (${response.status})`);
  return response.json();
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

async function removeActiveJob(jobId) {
  const jobs = await activeJobs();
  delete jobs[jobId];
  await saveActiveJobs(jobs);
}

async function finishJob(jobId, record, captured, closeTab) {
  await chrome.alarms.clear(`${JOB_ALARM_PREFIX}${jobId}`);
  await submit(jobId, captured);
  await removeActiveJob(jobId);
  if (closeTab) await chrome.tabs.remove(record.tabId).catch(() => {});
  await setStatus(captured.security_challenge ? 'attention' : 'connected', captured.security_challenge
    ? `Complete or inspect ${record.job.shop_key} in the open tab`
    : `Captured ${record.job.shop_key} for ${record.job.model}`);
  void pollLoop();
}

async function inspectJob(jobId) {
  if (inspecting.has(jobId)) return;
  inspecting.add(jobId);
  try {
    const record = (await activeJobs())[jobId];
    if (!record) return;
    const expired = Date.now() - record.startedAt >= JOB_TIMEOUT_MS;
    let captured;
    try {
      captured = await snapshot(record.tabId, record.job.model);
    } catch (error) {
      if (!expired) {
        await setStatus('working', `Waiting for ${record.job.shop_key} to finish loading`, { job: record.job });
        return;
      }
      captured = {
        url: record.job.url,
        html: '',
        security_challenge: true,
        error: String(error?.message || error)
      };
    }
    if ((captured.security_challenge || captured.incomplete) && !expired) {
      await heartbeat();
      await setStatus('attention', captured.security_challenge
        ? `Complete the visible ${record.job.shop_key} security check`
        : `Waiting for ${record.job.shop_key} content`, { job: record.job });
      return;
    }
    if (expired && (captured.security_challenge || captured.incomplete)) {
      captured.security_challenge = true;
      captured.error = 'Visible browser verification was not completed in time';
    }
    const { closeSuccessfulTabs } = await settings();
    await finishJob(jobId, record, captured, !captured.security_challenge && closeSuccessfulTabs);
  } catch (error) {
    await setStatus('attention', String(error?.message || error));
  } finally {
    inspecting.delete(jobId);
  }
}

async function acceptJob(job) {
  const tab = await chrome.tabs.create({ url: job.url, active: true });
  const jobs = await activeJobs();
  jobs[job.id] = { job, tabId: tab.id, startedAt: Date.now() };
  await saveActiveJobs(jobs);
  await chrome.alarms.create(`${JOB_ALARM_PREFIX}${job.id}`, { when: Date.now() + JOB_TIMEOUT_MS });
  await setStatus('working', `Opening ${job.shop_key} for ${job.model}`, { job });
  if (tab.status === 'complete') void inspectJob(job.id);
}

async function pollOnce() {
  const response = await bridgeFetch('/browser-bridge/jobs/next?wait_seconds=1');
  if (response.status === 204) return false;
  if (!response.ok) throw new Error(`PriceMonitor connection failed (${response.status})`);
  await acceptJob(await response.json());
  return true;
}

async function pollLoop() {
  if (socketOpen()) return;
  if (polling) return;
  polling = true;
  try {
    await heartbeat();
    let capacity = MAX_ACTIVE_JOBS - Object.keys(await activeJobs()).length;
    while (capacity > 0 && await pollOnce()) capacity -= 1;
    if (Object.keys(await activeJobs()).length === 0) await setStatus('connected', 'Connected to PriceMonitor');
  } catch (error) {
    await setStatus('disconnected', String(error?.message || error));
  } finally {
    polling = false;
  }
}

async function resumeJobs() {
  await heartbeat();
  for (const jobId of Object.keys(await activeJobs())) void inspectJob(jobId);
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
  void connectWebSocket();
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
  void connectWebSocket();
  void resumeJobs();
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name.startsWith(JOB_ALARM_PREFIX)) {
    void inspectJob(alarm.name.slice(JOB_ALARM_PREFIX.length));
    return;
  }
  if (alarm.name === POLL_ALARM) {
    void connectWebSocket();
    if (!socketOpen()) void resumeJobs().then(pollLoop).catch(error => setStatus('reconnecting', String(error)));
  }
});
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status !== 'complete') return;
  void activeJobs().then(jobs => {
    const match = Object.entries(jobs).find(([, record]) => record.tabId === tabId);
    if (match) void inspectJob(match[0]);
  });
});
chrome.tabs.onRemoved.addListener(tabId => {
  void activeJobs().then(async jobs => {
    const match = Object.entries(jobs).find(([, record]) => record.tabId === tabId);
    if (!match) return;
    const [jobId, record] = match;
    await chrome.alarms.clear(`${JOB_ALARM_PREFIX}${jobId}`);
    await submit(jobId, {
      url: record.job.url,
      html: '',
      security_challenge: true,
      error: 'The browser tab was closed before capture completed'
    }).catch(() => {});
    await removeActiveJob(jobId);
    void pollLoop();
  });
});
chrome.storage.onChanged.addListener(changes => {
  if (changes.appUrl) {
    bridgeSocket?.close();
    void connectWebSocket();
  }
});
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'connect') return false;
  connectWebSocket()
    .then(() => heartbeat())
    .then(() => sendResponse({ ok: true }))
    .catch(error => sendResponse({ ok: false, error: String(error?.message || error) }));
  return true;
});
void chrome.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
void connectWebSocket();
void resumeJobs().catch(error => setStatus('reconnecting', String(error)));
