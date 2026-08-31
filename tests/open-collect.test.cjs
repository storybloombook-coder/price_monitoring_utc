const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const URLS={salidzini:'https://www.salidzini.lv/cena?q=TCL+115RM9L',kaina24:'https://www.kaina24.lt/p/tcl-115rm9l/',hinnavaatlus:'https://www.hinnavaatlus.ee/123/tcl-115rm9l/'};
function harness() {
  const storage={activeJobs:{}},tabs=new Map(),closed=[],results=[],calls=[],alive=new Set(),updates=[],timers=[];
  let clock=1000,receipt={state:'pending'},receiptCode=200,challenge=false,ready=true,appUrl='http://127.0.0.1:8050',offline=false;
  const ctx=vm.createContext({URL,Map,AbortSignal,console,Date:class extends Date{static now(){return clock;}},
    POLL_ALARM:'poll',JOB_ALARM_PREFIX:'job:',setTimeout:fn=>{timers.push(fn);return timers.length;},
    serializeJob:fn=>fn(),settings:async()=>({appUrl}),inspectJob:async()=>{},setStatus:async()=>{},
    activeJobs:async()=>structuredClone(storage.activeJobs),saveActiveJobs:async jobs=>storage.activeJobs=structuredClone(jobs),
    removeActiveJob:async id=>delete storage.activeJobs[id],
    submit:async(id,payload)=>{results.push({id,payload});alive.delete(id);},
    finishJob:async(id,record,payload,close)=>{results.push({id,payload,close});alive.delete(id);delete storage.activeJobs[id];},
    snapshot:async id=>({url:tabs.get(id).url,html:'captured offers',security_challenge:challenge,
      salidzini_ready:ready,salidzini_fingerprint:'stable-cards',page_ready:ready,page_fingerprint:'stable-page'}),
    fetch:async url=>{
      calls.push(url);if(offline)throw Error('Failed to fetch');
      return url.endsWith('/status')?{ok:true,json:async()=>({jobs:[...alive].map(id=>({id,verification_id:'v'}))})}
        :{ok:receiptCode===200,status:receiptCode,json:async()=>receipt};
    },
    chrome:{storage:{local:{get:async key=>({...key,...structuredClone(storage)}),
      set:async values=>Object.assign(storage,structuredClone(values))}},
      alarms:{create:async()=>{},clear:async()=>{},onAlarm:{addListener(){}}},
      declarativeNetRequest:{updateSessionRules:async()=>{}},
      tabs:{onUpdated:{addListener:fn=>updates.push(fn)},create:async value=>{
        const tab={id:tabs.size+1,status:'complete',...value};tabs.set(tab.id,tab);return {...tab};
      },get:async id=>{if(!tabs.has(id))throw Error('No tab');return {...tabs.get(id)};},
      update:async(id,change)=>{Object.assign(tabs.get(id),change);return {...tabs.get(id)};},
      remove:async id=>{closed.push(id);tabs.delete(id);}}
    }
  });
  const run=code=>vm.runInContext(code,ctx);
  run(fs.readFileSync('edge-extension-v5/open-collect.js','utf8'));
  return {storage,tabs,closed,results,calls,run,updates,
    start:async(id='a',key='salidzini',url=URLS[key])=>{
      alive.add(id);return run(`acceptVerification(${JSON.stringify({id,verification_id:'v',model:'115RM9L',shop_key:key,url})})`);
    },inspect:id=>run(`inspectVerification('${id}',${JSON.stringify(storage.activeJobs[id])})`),watch:()=>run("watchVerification('v')"),
    receipt:value=>receipt=value,receiptCode:v=>receiptCode=v,challenge:v=>challenge=v,ready:v=>ready=v,
    advance:ms=>clock+=ms,offline:v=>offline=v,stop:()=>alive.clear(),app:v=>appUrl=v};
}

for(const key of Object.keys(URLS)) test(`${key}: receipt, not capture acknowledgement, permits closing`,async()=>{
  const h=harness();await h.start('a',key);assert.equal(h.tabs.get(1).active,true);
  await h.inspect('a');await h.inspect('a');assert.equal(h.results.length,1);assert.deepEqual(h.closed,[]);
  await h.watch();assert.deepEqual(h.closed,[]);
  h.receipt({state:'complete',status:'SUCCESS'});await h.watch();assert.deepEqual(h.closed,[1]);
});

test('CAPTCHA waits without reloading or submitting; collection resumes after completion',async()=>{
  const h=harness();await h.start();h.challenge(true);await h.inspect('a');
  h.advance(70000);await h.inspect('a');assert.equal(h.results.length,0);assert.equal(h.tabs.size,1);
  h.challenge(false);await h.inspect('a');await h.inspect('a');assert.equal(h.results.length,1);
  assert.equal(h.results[0].payload.html,'captured offers');assert.deepEqual(h.closed,[]);
});

test('all pages reuse one dedicated tab; no closure between pages',async()=>{
  const h=harness();await h.start();await h.inspect('a');await h.inspect('a');await h.watch();
  await h.start('b','salidzini',URLS.salidzini+'&offset=20');assert.equal(h.tabs.size,1);
  await h.inspect('b');await h.inspect('b');assert.equal(h.results.length,2);assert.deepEqual(h.closed,[]);
  h.receipt({state:'complete',status:'SUCCESS'});await h.watch();assert.deepEqual(h.closed,[1]);
});

for(const state of ['review','cancelled']) test(`${state}: preserve verification page`,async()=>{
  const h=harness();await h.start();h.stop();await h.inspect('a');h.receipt({state});await h.watch();
  assert.equal(h.results.length,0);assert.deepEqual(h.closed,[]);assert.equal(h.storage.verificationTabs.v,undefined);
});

test('confirmed Not found can close, but unconfirmed or unknown status cannot',async()=>{
  const h=harness();await h.start();h.receipt({state:'complete',status:'ACTION_REQUIRED'});await h.watch();assert.deepEqual(h.closed,[]);
  const empty=harness();await empty.start();empty.receipt({state:'complete',status:'NOT_FOUND'});await empty.watch();assert.deepEqual(empty.closed,[1]);
});

test('unknown layout and human wait have bounded timeouts without tab closure',async()=>{
  const h=harness();await h.start();h.ready(false);h.advance(31000);await h.inspect('a');
  assert.match(h.results[0].payload.error,/did not become ready/);assert.deepEqual(h.closed,[]);
  const captcha=harness();await captcha.start();captcha.challenge(true);captcha.advance(601000);await captcha.inspect('a');
  assert.match(captcha.results[0].payload.error,/10 minutes/);assert.deepEqual(captcha.closed,[]);
});

test('repurposed tab is never closed or reused even if the user navigates back',async()=>{
  const h=harness();await h.start();
  await h.updates[0](1,{url:'https://www.salidzini.lv/cena?q=TCL+25G64'});
  await new Promise(resolve=>setImmediate(resolve));
  h.receipt({state:'complete',status:'SUCCESS'});await h.watch();assert.deepEqual(h.closed,[]);
  const other=harness();await other.start();await other.inspect('a');await other.inspect('a');other.tabs.get(1).url='https://example.com/';
  await other.start('b');assert.match(other.results.at(-1).payload.error,/changed/);assert.equal(other.tabs.size,1);
});

test('offline, backend restart and changed app address preserve the tab',async()=>{
  const h=harness();await h.start();h.offline(true);await h.inspect('a');assert.equal(h.results.length,0);
  h.offline(false);h.receiptCode(404);await h.watch();assert.deepEqual(h.closed,[]);
  const other=harness();await other.start();const before=other.calls.length;other.app('http://127.0.0.1:9999');await other.inspect('a');await other.watch();
  assert.equal(other.calls.length,before);assert.equal(other.results.length,0);assert.deepEqual(other.closed,[]);
});

test('worker restart can resume a saved verification receipt',async()=>{
  const h=harness();await h.start();await h.inspect('a');await h.inspect('a');
  await h.run('resumeVerifications()');h.receipt({state:'complete',status:'SUCCESS'});await h.watch();assert.deepEqual(h.closed,[1]);
});

test('retailer and outbound redirect URLs are rejected before opening tabs',async()=>{
  const h=harness();await assert.rejects(h.start('a','salidzini','https://www.salidzini.lv/click.php?itemid=123'));
  await assert.rejects(h.start('b','kaina24','https://www.varle.lt/product'));
  assert.equal(h.tabs.size,0);
});
