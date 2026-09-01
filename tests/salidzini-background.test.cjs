const test=require('node:test'), assert=require('node:assert/strict'), vm=require('node:vm'), fs=require('node:fs');
const {webcrypto}=require('node:crypto');

test('worker imports both capture modules and queues WebSocket jobs behind cleanup',async()=>{
  const listeners=[], storage={}, noop=async()=>{};
  const event={addListener(){}};
  const ctx=vm.createContext({URL,TextEncoder,AbortSignal,crypto:webcrypto,console,setTimeout:()=>0,
    fetch:async()=>({ok:true,json:async()=>({connected:true})}),
    chrome:{
      storage:{local:{get:async key=>typeof key==='string'?{[key]:storage[key]}:{...key,...structuredClone(storage)},
        set:async value=>Object.assign(storage,structuredClone(value)),remove:async key=>delete storage[key]},onChanged:event},
      runtime:{id:'extension',getURL:path=>'chrome-extension://extension/'+path,getContexts:async()=>[{}],
        sendMessage:noop,onInstalled:event,onStartup:event,onMessage:{addListener:fn=>listeners.push(fn)}},
      action:{setBadgeText:noop,setBadgeBackgroundColor:noop},offscreen:{createDocument:noop},
      alarms:{create:noop,clear:noop,onAlarm:event},tabs:{onUpdated:event,onRemoved:event},
    }
  });
  ctx.importScripts=file=>vm.runInContext(fs.readFileSync('edge-extension-v5/'+file,'utf8'),ctx);
  vm.runInContext(fs.readFileSync('edge-extension-v5/background.js','utf8'),ctx);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(vm.runInContext('typeof acceptAutomaticSalidzini',ctx),'function');
  assert.equal(vm.runInContext('typeof handlePageCapture',ctx),'function');
  const source=fs.readFileSync('edge-extension-v5/background.js','utf8');
  assert.match(source,/querySelectorAll\('\.item_box_sub'\)/);
  assert.match(source,/salidzini_card_count: cards\.length/);
  storage.activeJobs={old:{job:{id:'old'}}};
  let release;
  ctx.cleanupGate=new Promise(resolve=>release=resolve);
  ctx.accepted=[];
  vm.runInContext('acceptJobNow = async job => accepted.push(job.id); serializeJob(()=>cleanupGate)',ctx);
  listeners[0]({target:'service-worker',type:'job',job:{id:'next'}},{},()=>{});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(ctx.accepted,[]);
  release();
  await vm.runInContext('jobWork',ctx);
  assert.deepEqual(ctx.accepted,['next']);
});
