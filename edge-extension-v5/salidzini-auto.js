// One owned tab, bounded loading, no CAPTCHA clicks and no retailer navigation.
const SALIDZINI_AUTO_TIMEOUT = 20000;
const salidziniTimers = new Map();

function sameSalidziniSearch(first, second) {
  try {
    const a = new URL(salidziniPage(first)), b = new URL(salidziniPage(second));
    a.searchParams.sort(); b.searchParams.sort();
    return a.searchParams.toString() === b.searchParams.toString();
  } catch { return false; }
}

function salidziniLater(jobId) {
  if (salidziniTimers.has(jobId)) return;
  salidziniTimers.set(jobId, setTimeout(() => {
    salidziniTimers.delete(jobId);
    void inspectJob(jobId);
  }, 1200));
}

async function automaticJobAlive(record) {
  if ((await settings()).appUrl !== record.appUrl) return false;
  const response = await bridgeFetch('/browser-bridge/status', {signal:AbortSignal.timeout(4000)});
  if (!response.ok) throw new Error('Cannot check the active PriceMonitor job');
  return (await response.json()).jobs.some(job => job.id === record.job.id);
}

async function discardAutomaticJob(jobId, record) {
  await chrome.alarms.clear(`${JOB_ALARM_PREFIX}${jobId}`);
  await removeActiveJob(jobId);
  if (record.ruleId) await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds:[record.ruleId]});
}

async function acceptAutomaticSalidzini(job) {
  salidziniPage(job.url);
  const appUrl = (await settings()).appUrl;
  const pending = {job, appUrl};
  if (!await automaticJobAlive(pending)) return; // Stop/clear can precede delivery.
  let tab;
  const saved = (await chrome.storage.local.get('salidziniAutoTab')).salidziniAutoTab;
  if (saved?.appUrl === appUrl) {
    try {
      const candidate = await chrome.tabs.get(saved.id);
      if (candidate.url === 'about:blank' || salidziniPage(candidate.url)) tab = candidate;
    } catch { /* Closed or repurposed user tab: do not navigate it. */ }
  }
  if (!tab) tab = await chrome.tabs.create({url:'about:blank',active:false});
  const ruleId = tab.id + 100000;
  await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds:[ruleId],addRules:[{
    id:ruleId,priority:1,action:{type:'block'},condition:{tabIds:[tab.id],resourceTypes:['main_frame'],excludedRequestDomains:['salidzini.lv']}
  }]});
  await chrome.storage.local.set({salidziniAutoTab:{id:tab.id,appUrl}});
  const record = {...pending,tabId:tab.id,ruleId,startedAt:Date.now(),automatic:true};
  const jobs = await activeJobs(); jobs[job.id] = record; await saveActiveJobs(jobs);
  if (!await automaticJobAlive(record)) { await discardAutomaticJob(job.id,record); return; }
  await chrome.tabs.update(tab.id,{url:job.url});
  await chrome.alarms.create(`${JOB_ALARM_PREFIX}${job.id}`,{when:Date.now()+SALIDZINI_AUTO_TIMEOUT});
  await setStatus('working',`Salidzini Auto · ${job.model}`);
  salidziniLater(job.id);
}

async function inspectAutomaticSalidzini(jobId, record) {
  const expired = Date.now()-record.startedAt >= SALIDZINI_AUTO_TIMEOUT;
  try {
    if (!await automaticJobAlive(record)) {
      await discardAutomaticJob(jobId,record);
      // Stop the extension-owned navigation; never close a user's verification tab.
      const saved = (await chrome.storage.local.get('salidziniAutoTab')).salidziniAutoTab;
      if (saved?.id === record.tabId) await chrome.tabs.update(record.tabId,{url:'about:blank'}).catch(()=>{});
      return;
    }
    const tab = await chrome.tabs.get(record.tabId);
    if (tab.status !== 'complete') {
      if (!expired) { salidziniLater(jobId); return; }
      throw new Error('Page loading timed out');
    }
    const captured = await snapshot(record.tabId,record.job.model);
    if (captured.security_challenge) {
      await chrome.tabs.update(record.tabId,{active:true});
      await finishJob(jobId,record,{...captured,error:'CAPTCHA detected. Complete it manually in this tab'},false);
      // Preserve this tab for the user; future automation uses a new owned tab.
      await chrome.storage.local.remove('salidziniAutoTab');
      return;
    }
    if (!sameSalidziniSearch(captured.url, record.job.url)) throw new Error('Search page changed or redirected unexpectedly');
    if (captured.incomplete) throw new Error('Page exceeds the capture size limit');
    if (!captured.salidzini_ready || record.fingerprint !== captured.salidzini_fingerprint) {
      if (expired) throw new Error('Results did not become ready; inspect the page manually');
      const jobs = await activeJobs();
      if (jobs[jobId]) { jobs[jobId].fingerprint = captured.salidzini_fingerprint; await saveActiveJobs(jobs); }
      salidziniLater(jobId); return;
    }
    await finishJob(jobId,record,captured,false); // Retain the owned tab for the next page/SKU.
  } catch (error) {
    if (!expired && /fetch|network|active PriceMonitor/i.test(String(error.message))) { salidziniLater(jobId); return; }
    await finishJob(jobId,record,{url:record.job.url,html:'',error:String(error.message),security_challenge:false},false);
  }
}
