// Click-scoped verification. Only a final, saved backend receipt can close a tab.
const VERIFY_PAGE_MS = 30000;
const VERIFY_HUMAN_MS = 600000;
const verifyTimers = new Map();

function verificationPage(value, key) {
  const domains={kaina24:'kaina24.lt',salidzini:'salidzini.lv',hinnavaatlus:'hinnavaatlus.ee'};
  const url=new URL(value), domain=domains[key], path=decodeURIComponent(url.pathname);
  if (!domain || url.protocol!=='https:' || ![domain,`www.${domain}`].includes(url.hostname) ||
      url.username || url.password || (url.port && url.port!=='443') ||
      /(?:^|\/)(?:ex|out|go|click|redirect|redirector|shop|poodi|offer)(?:[/.]|$)/i.test(path) ||
      /(?:^|&)(?:url|redirect|target|to)=/i.test(url.search.slice(1))) throw new Error('Use a marketplace comparison page');
  return url;
}

function sameVerificationPage(first, second, key) {
  try {
    const a=verificationPage(first,key),b=verificationPage(second,key);
    a.searchParams.sort(); b.searchParams.sort();
    return a.pathname.replace(/\/$/,'')===b.pathname.replace(/\/$/,'') && a.searchParams.toString()===b.searchParams.toString();
  } catch { return false; }
}

async function verificationTabs() {
  return (await chrome.storage.local.get({verificationTabs:{}})).verificationTabs;
}

function verifyLater(id, session=false) {
  const key=(session?'session:':'page:')+id;
  if (verifyTimers.has(key)) return;
  verifyTimers.set(key,setTimeout(()=>{
    verifyTimers.delete(key);
    if (session) void serializeJob(()=>watchVerification(id)).catch(()=>verifyLater(id,true));
    else void inspectJob(id);
  },1200));
}

async function verificationFetch(record, path) {
  if ((await settings()).appUrl!==record.appUrl) throw new Error('PriceMonitor address changed');
  // Pin every request to the app that issued the action, including reconnects.
  return fetch(record.appUrl+path,{cache:'no-store',signal:AbortSignal.timeout(4000)});
}

async function verificationJobAlive(record) {
  const response=await verificationFetch(record,'/browser-bridge/status');
  if (!response.ok) throw new Error('Cannot check the active verification job');
  return (await response.json()).jobs.some(job=>job.id===record.job.id && job.verification_id===record.job.verification_id);
}

async function releaseVerification(id, session) {
  if (session.ruleId) await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds:[session.ruleId]});
  const sessions=await verificationTabs(); delete sessions[id];
  await chrome.storage.local.set({verificationTabs:sessions});
}

async function watchVerification(id) {
  const session=(await verificationTabs())[id];
  if (!session) return;
  if ((await settings()).appUrl!==session.appUrl || Date.now()-session.startedAt>960000) {
    await releaseVerification(id,session); return; // Never close on disconnect/expiry.
  }
  try {
    const response=await verificationFetch(session,`/browser-bridge/verifications/${encodeURIComponent(id)}`);
    if (response.status===404) { await releaseVerification(id,session); return; } // App restarted.
    if (!response.ok) throw new Error('Waiting for the saved result');
    const receipt=await response.json();
    if (receipt.state==='pending') { verifyLater(id,true); return; }
    // The collector publishes complete only after the final database commit.
    if (receipt.state==='complete' && ['SUCCESS','NOT_FOUND'].includes(receipt.status)) {
      const tab=await chrome.tabs.get(session.tabId).catch(()=>null);
      if (tab && !session.detached && sameVerificationPage(tab.url,session.lastUrl,session.key) &&
          (await settings()).appUrl===session.appUrl) await chrome.tabs.remove(session.tabId);
      await setStatus('connected',`Saved ${session.model} · ${session.key}`);
    } else {
      await setStatus('attention',receipt.error || 'Verification needs review; the page has been kept open');
    }
    await releaseVerification(id,session);
  } catch { verifyLater(id,true); }
}

async function acceptVerification(job) {
  verificationPage(job.url,job.shop_key);
  const record={job,appUrl:(await settings()).appUrl,startedAt:Date.now(),interactive:true};
  if (!await verificationJobAlive(record)) return;
  const sessions=await verificationTabs();
  let session=sessions[job.verification_id],tab;
  if (session) {
    tab=await chrome.tabs.get(session.tabId).catch(()=>null);
    if (!tab || session.detached || session.appUrl!==record.appUrl || !sameVerificationPage(tab.url,session.lastUrl,job.shop_key)) {
      await submit(job.id,{url:job.url,html:'',error:'Verification tab was closed or changed; open a new check'});
      verifyLater(job.verification_id,true); return;
    }
  } else {
    // A fresh owned tab, never a matching pre-existing user tab.
    tab=await chrome.tabs.create({url:'about:blank',active:true});
    session={tabId:tab.id,appUrl:record.appUrl,key:job.shop_key,model:job.model,startedAt:Date.now()};
  }
  Object.assign(record,{tabId:tab.id,ruleId:tab.id+200000,loadStartedAt:Date.now()});
  session.lastUrl=job.url; session.ruleId=record.ruleId;
  sessions[job.verification_id]=session;
  await chrome.storage.local.set({verificationTabs:sessions});
  const domain=verificationPage(job.url,job.shop_key).hostname.replace(/^www\./,'');
  await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds:[record.ruleId],addRules:[{
    id:record.ruleId,priority:1,action:{type:'block'},condition:{tabIds:[tab.id],resourceTypes:['main_frame'],excludedRequestDomains:[domain]}
  }]});
  const jobs=await activeJobs();jobs[job.id]=record;await saveActiveJobs(jobs);
  if (!await verificationJobAlive(record)) {
    await removeActiveJob(job.id);verifyLater(job.verification_id,true);return;
  }
  await chrome.tabs.update(tab.id,{url:job.url});
  await chrome.alarms.create(`${JOB_ALARM_PREFIX}${job.id}`,{when:Date.now()+VERIFY_HUMAN_MS});
  await setStatus('working',`Open & collect · ${job.model} · complete CAPTCHA if shown`);
  verifyLater(job.id);verifyLater(job.verification_id,true);
}

async function inspectVerification(jobId, record) {
  try {
    if (!await verificationJobAlive(record)) {
      await removeActiveJob(jobId);await chrome.alarms.clear(`${JOB_ALARM_PREFIX}${jobId}`);
      verifyLater(record.job.verification_id,true);return;
    }
    const now=Date.now();
    if (now-record.startedAt>=VERIFY_HUMAN_MS) throw new Error('Verification timed out after 10 minutes; the page stays open for manual entry');
    const tab=await chrome.tabs.get(record.tabId);
    if (tab.status!=='complete') {
      if (now-record.loadStartedAt>VERIFY_PAGE_MS && !record.challengeSeen) throw new Error('Page loading timed out; inspect it manually');
      verifyLater(jobId);return;
    }
    const captured=await snapshot(record.tabId,record.job.model);
    if (captured.security_challenge) {
      const jobs=await activeJobs();
      if (jobs[jobId]) Object.assign(jobs[jobId],{loadStartedAt:now,challengeSeen:true,fingerprint:null});
      await saveActiveJobs(jobs);
      await setStatus('attention',`Complete ${record.job.shop_key} verification in the open tab; collection resumes automatically`);
      verifyLater(jobId);return; // Never click, reload or submit a CAPTCHA page.
    }
    if (!sameVerificationPage(captured.url,record.job.url,record.job.shop_key)) throw new Error('Verification page changed; check the SKU before saving');
    if (captured.incomplete) throw new Error('Page is too large for a reliable capture');
    const ready=record.job.shop_key==='salidzini'?captured.salidzini_ready:captured.page_ready;
    const fingerprint=record.job.shop_key==='salidzini'?captured.salidzini_fingerprint:captured.page_fingerprint;
    if (!ready || record.fingerprint!==fingerprint) {
      if (now-record.loadStartedAt>VERIFY_PAGE_MS) throw new Error('Results did not become ready; inspect this page manually');
      const jobs=await activeJobs();if(jobs[jobId]) jobs[jobId].fingerprint=fingerprint;
      await saveActiveJobs(jobs);verifyLater(jobId);return;
    }
    await finishJob(jobId,record,captured,false);
    verifyLater(record.job.verification_id,true);
  } catch (error) {
    if (/fetch|network|active verification|Failed to fetch/i.test(String(error.message)) && Date.now()-record.startedAt<VERIFY_HUMAN_MS) {
      verifyLater(jobId);return;
    }
    if ((await settings()).appUrl!==record.appUrl) {
      await removeActiveJob(jobId);verifyLater(record.job.verification_id,true);return;
    }
    try { await finishJob(jobId,record,{url:record.job.url,html:'',error:String(error.message)},false); }
    catch { verifyLater(jobId); }
    verifyLater(record.job.verification_id,true);
  }
}

async function resumeVerifications() {
  for (const id of Object.keys(await verificationTabs())) verifyLater(id,true);
}

chrome.tabs.onUpdated.addListener((tabId,change)=>{
  if (!change.url || change.url==='about:blank') return;
  void serializeJob(async()=>{
    const sessions=await verificationTabs();let changed=false;
    for (const session of Object.values(sessions)) {
      if (session.tabId===tabId && !sameVerificationPage(change.url,session.lastUrl,session.key)) { session.detached=true;changed=true; }
    }
    if(changed) await chrome.storage.local.set({verificationTabs:sessions});
  });
});
chrome.alarms.onAlarm.addListener(alarm=>{
  if(alarm.name===POLL_ALARM) void resumeVerifications();
});
void resumeVerifications();
