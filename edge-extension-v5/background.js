const DEFAULT_APP_URL = 'http://127.0.0.1:8050';
const POLL_ALARM = 'price-monitor-poll';
const MAX_ACTIVE_JOBS = 1;
const JOB_TIMEOUT_MS = 60000;
const JOB_ALARM_PREFIX = 'price-monitor-job:';
const OFFSCREEN_PATH = 'offscreen.html';
let polling = false;
const inspecting = new Set();
let creatingOffscreen = null;
let jobWork = Promise.resolve();
function serializeJob(work) {
  const next = jobWork.then(work, work); jobWork = next.catch(()=>{}); return next;
}

async function settings() {
  const saved = await chrome.storage.local.get({ appUrl: DEFAULT_APP_URL, closeSuccessfulTabs: true, clientId: '' });
  const clientId = saved.clientId || globalThis.crypto?.randomUUID?.() || `browser-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  if (!saved.clientId) await chrome.storage.local.set({ clientId });
  const userAgent = typeof navigator === 'undefined' ? '' : navigator.userAgent;
  const browserName = /Edg\//.test(userAgent) ? 'Edge' : /Firefox\//.test(userAgent) ? 'Firefox' : 'Chrome';
  return { ...saved, clientId, browserName, appUrl: String(saved.appUrl || DEFAULT_APP_URL).replace(/\/$/, '') };
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

async function ensureOffscreenDocument() {
  const offscreenUrl = chrome.runtime.getURL(OFFSCREEN_PATH);
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT'],
    documentUrls: [offscreenUrl]
  });
  if (contexts.length) return;
  if (!creatingOffscreen) {
    creatingOffscreen = chrome.offscreen.createDocument({
      url: OFFSCREEN_PATH,
      reasons: ['WORKERS'],
      justification: 'Maintain the local PriceMonitor connection in a dedicated worker'
    }).finally(() => { creatingOffscreen = null; });
  }
  await creatingOffscreen;
}

async function configureLiveChannel() {
  await ensureOffscreenDocument();
  const { appUrl, clientId, browserName } = await settings();
  const jobs = await activeJobs();
  await chrome.runtime.sendMessage({
    target: 'offscreen', type: 'configure', appUrl, clientId, browserName, activeJobIds: Object.keys(jobs)
  }).catch(() => {});
}

async function liveChannelConnected() {
  const saved = await chrome.storage.local.get({ offscreenSocketState: null });
  const state = saved.offscreenSocketState;
  return Boolean(state?.connected && Date.now() - Number(state.updatedAt || 0) < 45000);
}

async function heartbeat() {
  const { clientId, browserName } = await settings();
  const response = await bridgeFetch(`/browser-bridge/heartbeat?auto_salidzini=true&open_collect=true&client_id=${encodeURIComponent(clientId)}&browser_name=${encodeURIComponent(browserName)}`, { method: 'POST' });
  if (!response.ok) throw new Error(`PriceMonitor connection failed (${response.status})`);
  return response.json();
}

function extractRenderedPage(model) {
  const text = document.body?.innerText || '';
  const securityChallenge = /verify you are human|just a moment|checking your browser/i.test(text) ||
    [...document.querySelectorAll('#challenge-running, #challenge-stage, .h-captcha iframe, iframe[src*="hcaptcha.com"][title*="challenge"]')]
      .some(node=>{const box=node.getBoundingClientRect(),style=getComputedStyle(node);return box.width>0 && box.height>0 && style.display!=='none' && style.visibility!=='hidden';});
  const clone = document.documentElement.cloneNode(true);
  clone.querySelectorAll('script:not([type="application/ld+json"]), style, svg, noscript, input, textarea, select, iframe').forEach(node => node.remove());
  const html = clone.outerHTML;
  // Salidzini currently serves both outer and inner card layouts. Prefer the
  // outer cards to avoid duplicates, but accept inner-only pages as ready.
  const mainCards = [...document.querySelectorAll('.item_box_main')];
  const cards = mainCards.length ? mainCards : [...document.querySelectorAll('.item_box_sub')];
  const empty = /\b0\s+preces?\b|nekas netika atrasts|preces? nav atrastas?|nav atrasta neviena prece|meklēšanas rezultāti nav atrasti|nav meklēšanas rezultātu|\b0\s+rezultāti\b/i.test(text) ||
    Boolean(document.querySelector('.no-results, .search-no-results, .search_no_results, #no-results, #no_results'));
  // Use stable offer evidence rather than all visible text. Delivery clocks,
  // adverts and stock labels can update while the seller prices are complete.
  const fingerprint = cards.map(node => {
    const link = node.querySelector('.item_link')?.getAttribute('href') || '';
    const seller = node.querySelector('.item_shop_name, .shop_name, .seller-name')?.textContent?.trim() || '';
    const price = node.querySelector('.item_price, .price, .offer-price')?.textContent?.trim() || '';
    return `${link}|${seller}|${price}`;
  }).join('||');
  const resultNodes=[...document.querySelectorAll('.product-item-h-wrap, .seller-item-table, tr.offer, .product-name')];
  // Ads/clocks outside the offer list must not prevent stable result detection.
  const resultText=resultNodes.length ? (document.querySelector('h1')?.innerText||'')+'|'+resultNodes.map(n=>n.innerText).join('|') : text;
  let textHash=2166136261;
  for(let i=0;i<resultText.length;i++) textHash=Math.imul(textHash^resultText.charCodeAt(i),16777619);
  return { url: location.href, title: document.title, html: html.slice(0, 7900000),
    security_challenge: securityChallenge, incomplete: html.length > 7900000,
    salidzini_ready: document.readyState === 'complete' && (cards.length > 0 || empty),
    salidzini_fingerprint: fingerprint || (empty ? 'empty' : ''),
    salidzini_card_count: cards.length, page_text_length: text.length,
    ready_state: document.readyState,
    page_ready:document.readyState==='complete' && text.trim().length>50,
    page_fingerprint:String(textHash>>>0) };
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
  const { clientId } = await settings();
  const response = await bridgeFetch(`/browser-bridge/jobs/${encodeURIComponent(jobId)}/result?client_id=${encodeURIComponent(clientId)}`, {
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
  return serializeJob(() => finishJobNow(jobId, record, captured, closeTab));
}
async function finishJobNow(jobId, record, captured, closeTab) {
  await chrome.alarms.clear(`${JOB_ALARM_PREFIX}${jobId}`);
  await submit(jobId, captured);
  await removeActiveJob(jobId);
  if (record.ruleId && !record.interactive) await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds: [record.ruleId]});
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
    if (record.interactive) { await inspectVerification(jobId,record); return; }
    if (record.automatic) { await inspectAutomaticSalidzini(jobId,record); return; }
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
  return serializeJob(() => acceptJobNow(job));
}
async function acceptJobNow(job) {
  if ((await activeJobs())[job.id]) { void inspectJob(job.id); return; }
  const domains = {kaina24:'kaina24.lt', salidzini:'salidzini.lv', hinnavaatlus:'hinnavaatlus.ee'};
  const domain = domains[job.shop_key];
  const url = new URL(job.url);
  if (!domain || url.protocol !== 'https:' || ![domain, `www.${domain}`].includes(url.hostname) || url.username || url.password || (url.port && url.port !== '443')) throw new Error('Only marketplace comparison pages are allowed');
  if (job.verification_id) { await acceptVerification(job); return; }
  if (job.shop_key === 'salidzini') {
    if (job.automatic) { await acceptAutomaticSalidzini(job); return; }
    const tabs = await chrome.tabs.query({ url: ['https://salidzini.lv/*', 'https://www.salidzini.lv/*'] });
    const existing = tabs.find(tab => tab.url === job.url);
    if (existing) await chrome.tabs.update(existing.id, { active: true });
    else await chrome.tabs.create({ url: job.url, active: true });
    // Release the timed monitoring job. The user's tab and explicit page capture
    // remain usable indefinitely, even after this run completes or reconnects.
    await submit(job.id, { url: job.url, html: '', security_challenge: true,
      error: 'Complete Salidzini CAPTCHA, then click Send to PriceMonitor in the extension. No time limit; review captured prices before saving.' });
    await setStatus('attention', 'Salidzini is ready for manual verification and Send to PriceMonitor');
    return;
  }
  const tab = await chrome.tabs.create({ url: 'about:blank', active: true });
  const ruleId = tab.id + 100000;
  await chrome.declarativeNetRequest.updateSessionRules({addRules: [{id:ruleId, priority:1, action:{type:'block'}, condition:{tabIds:[tab.id], resourceTypes:['main_frame'], excludedRequestDomains:[domain]}}]});
  const jobs = await activeJobs();
  jobs[job.id] = { job, tabId: tab.id, ruleId, startedAt: Date.now() };
  await saveActiveJobs(jobs);
  await chrome.tabs.update(tab.id, {url:job.url});
  await chrome.alarms.create(`${JOB_ALARM_PREFIX}${job.id}`, { when: Date.now() + JOB_TIMEOUT_MS });
  await setStatus('working', `Opening ${job.shop_key} for ${job.model}`, { job });
  if (tab.status === 'complete') void inspectJob(job.id);
}

async function pollOnce() {
  const { clientId, browserName } = await settings();
  const response = await bridgeFetch(`/browser-bridge/jobs/next?wait_seconds=1&client_id=${encodeURIComponent(clientId)}&browser_name=${encodeURIComponent(browserName)}`);
  if (response.status === 204) return false;
  if (!response.ok) throw new Error(`PriceMonitor connection failed (${response.status})`);
  await acceptJob(await response.json());
  return true;
}

async function pollLoop() {
  if (await liveChannelConnected()) return;
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
  await resumeVerifications();
  for (const jobId of Object.keys(await activeJobs())) void inspectJob(jobId);
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
  void configureLiveChannel();
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
  void configureLiveChannel();
  void resumeJobs();
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name.startsWith(JOB_ALARM_PREFIX)) {
    void inspectJob(alarm.name.slice(JOB_ALARM_PREFIX.length));
    return;
  }
  if (alarm.name === POLL_ALARM) {
    void configureLiveChannel();
    void liveChannelConnected().then(connected => {
      if (!connected) void resumeJobs().then(pollLoop).catch(error => setStatus('reconnecting', String(error)));
    });
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
  if (changes.appUrl) void configureLiveChannel();
});
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.target === 'service-worker') {
    if (message.type === 'offscreen-ready') {
      void configureLiveChannel();
    } else if (message.type === 'socket-state') {
      void chrome.storage.local.set({ offscreenSocketState: message });
      void setStatus(message.connected ? 'connected' : 'reconnecting', message.message || 'Updating live channel…');
      if (message.connected) void resumeJobs().catch(() => {});
    } else if (message.type === 'job' && message.job) {
      // The backend has one capture slot. A new job may arrive while the
      // previous result is acknowledged but its local cleanup is still running.
      // Queue behind that cleanup instead of silently dropping the new job.
      void acceptJob(message.job).catch(error => setStatus('attention', String(error?.message || error)));
    }
    return false;
  }
  if (message?.type !== 'connect') return false;
  configureLiveChannel()
    .then(() => heartbeat())
    .then(() => sendResponse({ ok: true }))
    .catch(error => sendResponse({ ok: false, error: String(error?.message || error) }));
  return true;
});
void chrome.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
importScripts('page-capture.js');
importScripts('salidzini-auto.js');
importScripts('open-collect.js');
void configureLiveChannel();
void resumeJobs().catch(error => setStatus('reconnecting', String(error)));
