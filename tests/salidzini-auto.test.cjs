const test=require('node:test'), assert=require('node:assert/strict'), vm=require('node:vm'), fs=require('node:fs');
const URL1='https://www.salidzini.lv/cena?q=TCL+115RM9L';
function harness() {
  const storage={activeJobs:{}}, tabs=new Map(), navigations=[], results=[], timers=[];
  let clock=1000,alive=true,challenge=false,ready=true,changedUrl=false,active=true,appUrl='http://127.0.0.1:8050';
  const local={get:async key=>typeof key==='string'?{[key]:storage[key]}:{...key,...structuredClone(storage)},
    set:async value=>Object.assign(storage,structuredClone(value)),remove:async key=>delete storage[key]};
  const ctx=vm.createContext({URL,Map,AbortSignal,console,Date:class extends Date{static now(){return clock;}},
    JOB_ALARM_PREFIX:'job:',setTimeout:fn=>{timers.push(fn);return timers.length;},
    settings:async()=>({appUrl,clientId:'browser-1'}),activeJobs:async()=>structuredClone(storage.activeJobs),
    saveActiveJobs:async jobs=>{storage.activeJobs=structuredClone(jobs);},
    removeActiveJob:async id=>{delete storage.activeJobs[id];},setStatus:async()=>{},inspectJob:async()=>{},
    salidziniPage:value=>{const u=new URL(value); if(u.hostname!=='www.salidzini.lv'||u.pathname!=='/cena')throw Error('wrong page');return u.href;},
    bridgeFetch:async()=>({ok:true,json:async()=>({active_client_id:active?'browser-1':'browser-2',jobs:alive?[{id:'a',assigned_client_id:'browser-1'},{id:'b',assigned_client_id:'browser-1'}]:[]})}),
    snapshot:async id=>({url:changedUrl?'https://shop.test/':tabs.get(id).url,html:'real DOM snapshot',security_challenge:challenge,
      salidzini_ready:ready,salidzini_fingerprint:'cards',salidzini_card_count:ready?2:0,
      page_text_length:ready?500:0,ready_state:'complete',title:'Salidzini results',incomplete:false}),
    finishJob:async(id,record,payload,close)=>{results.push({id,record,payload,close});delete storage.activeJobs[id];},
    chrome:{storage:{local},alarms:{clear:async()=>{},create:async()=>{}},declarativeNetRequest:{updateSessionRules:async()=>{}},tabs:{
      get:async id=>{if(!tabs.has(id))throw Error('closed');return {...tabs.get(id)};},
      create:async value=>{const tab={id:tabs.size+1,status:'complete',...value};tabs.set(tab.id,tab);return {...tab};},
      update:async(id,change)=>{navigations.push({id,...change});Object.assign(tabs.get(id),change);return {...tabs.get(id)};},
      remove:async id=>{tabs.delete(id);}
    }}
  });
  vm.runInContext(fs.readFileSync('edge-extension-v5/salidzini-auto.js','utf8'),ctx);
  const run=code=>vm.runInContext(code,ctx);
  const start=id=>run(`acceptAutomaticSalidzini({id:'${id}',shop_key:'salidzini',model:'115RM9L',url:'${URL1}',automatic:true})`);
  const inspect=id=>run(`inspectAutomaticSalidzini('${id}', ${JSON.stringify(storage.activeJobs[id])})`);
  return {storage,tabs,navigations,results,start,inspect,setAlive:v=>alive=v,setActive:v=>active=v,setChallenge:v=>challenge=v,setReady:v=>ready=v,
    expire:()=>clock+=31000,setChangedUrl:v=>changedUrl=v,setApp:v=>appUrl=v};
}
test('automatically captures stable results, reuses one tab, requires no popup clicks',async()=>{
  const h=harness();await h.start('a');assert.equal(h.tabs.size,1);assert.equal(h.tabs.get(1).active,false);
  await h.inspect('a');assert.equal(h.results.length,0);
  await h.inspect('a');assert.equal(h.results.length,1);assert.equal(h.results[0].payload.html,'real DOM snapshot');assert.equal(h.results[0].close,false);
  await h.start('b');assert.equal(h.tabs.size,1);assert.equal(h.navigations.filter(n=>n.url===URL1).length,2);
});
test('CAPTCHA immediately releases job, activates verification tab, never clicks challenge',async()=>{
  const h=harness();await h.start('a');h.setChallenge(true);await h.inspect('a');
  assert.equal(h.results[0].payload.security_challenge,true);assert.match(h.results[0].payload.error,/CAPTCHA/);
  assert.equal(h.tabs.get(1).active,true);assert.equal(h.storage.salidziniAutoTab,undefined);
});
test('stopped job cannot open a new page; in-flight stop discards capture',async()=>{
  const h=harness();h.setAlive(false);await h.start('a');assert.equal(h.tabs.size,0);
  h.setAlive(true);await h.start('a');h.setAlive(false);await h.inspect('a');
  assert.equal(h.results.length,0);assert.equal(h.storage.activeJobs.a,undefined);assert.equal(h.tabs.has(1),false);
});
test('standby browser discards stale work before navigation or submission',async()=>{
  const h=harness();h.setActive(false);await h.start('a');assert.equal(h.tabs.size,0);assert.equal(h.results.length,0);
});
test('repurposed owned tab is left alone and a new one is used',async()=>{
  const h=harness();await h.start('a');await h.inspect('a');await h.inspect('a');h.tabs.get(1).url='https://shop.test/';
  await h.start('b');assert.equal(h.tabs.size,2);assert.equal(h.tabs.get(1).url,'https://shop.test/');
});
test('unknown readiness times out instead of endless checking',async()=>{
  const h=harness();await h.start('a');h.setReady(false);await h.inspect('a');h.expire();await h.inspect('a');
  assert.match(h.results[0].payload.error,/did not become ready/);assert.equal(h.results[0].payload.security_challenge,false);
  assert.equal(JSON.stringify(h.results[0].payload.page_diagnostics),JSON.stringify({title:'Salidzini results',ready_state:'complete',card_count:0,text_length:0,fingerprint:'cards'}));
});
test('redirected page and changed app origin cannot submit scraped data',async()=>{
  const h=harness();await h.start('a');h.setChangedUrl(true);await h.inspect('a');assert.match(h.results[0].payload.error,/redirected/);
  const other=harness();await other.start('a');other.setApp('http://127.0.0.1:9999');await other.inspect('a');assert.equal(other.results.length,0);
});
