const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const { webcrypto } = require('node:crypto');
const source = fs.readFileSync('edge-extension-v5/page-capture.js', 'utf8');

async function harness() {
  const storage = {};
  const calls = [];
  let online = true, failSaveAck = false, challenge = false, appUrl = 'http://127.0.0.1:8050', status = 200;
  const receipts = new Set();
  const context = vm.createContext({ URL, TextEncoder, AbortSignal, crypto: webcrypto, console,
    POLL_ALARM: 'poll', settings: async () => ({appUrl}),
    snapshot: async () => ({url: 'https://www.salidzini.lv/cena?q=TCL+25G64', html: '<div>captured page</div>', security_challenge: challenge}),
    chrome: { storage: {local: {
      get: async defaults => ({...defaults, ...structuredClone(storage)}),
      set: async value => Object.assign(storage, structuredClone(value))
    }}, tabs: {get: async () => ({id: 1, url: 'https://www.salidzini.lv/cena?q=TCL+25G64'})},
    runtime: {id: 'extension', onMessage: {addListener() {}}}, alarms: {onAlarm: {addListener() {}}}},
    fetch: async (url, options) => {
      calls.push(url);
      if (!online) throw new Error('offline');
      if (status !== 200) return {ok: false, status, json: async () => ({detail: 'Refresh preview'})};
      if (url.endsWith('page-apply')) {
        receipts.add(JSON.parse(options.body).capture_id);
        if (failSaveAck) { failSaveAck = false; throw new Error('ack lost'); }
        return {ok: true, json: async () => ({saved: 2, model: '25G64', status: 'SUCCESS'})};
      }
      return {ok: true, json: async () => ({run_id: 'run', item_id: 1, expected_signature: 'sig', offers: [{price_eur: 199}, {price_eur: 249}], next_pages: []})};
    }
  });
  vm.runInContext(source, context);
  await vm.runInContext('captureWork', context);
  const run = code => vm.runInContext(code, context);
  return { storage, calls, receipts, run, setOnline: v => {online = v;}, setChallenge: v => {challenge = v;},
    setApp: v => {appUrl = v;}, setStatus: v => {status = v;}, loseAck: () => {failSaveAck = true;} };
}

test('offline snapshot survives; reconnect previews only, never silently applies', async () => {
  const h = await harness(); h.setOnline(false);
  await h.run("handlePageCapture({type:'capture-current',tabId:1,model:'25G64'})");
  assert.equal(h.storage.pageCaptures.length, 1);
  assert.equal(h.storage.pageCaptures[0].state, 'queued');
  assert.ok(h.storage.pageCaptures[0].payload.html);
  h.setOnline(true); await h.run('flushPageCaptures()');
  assert.equal(h.storage.pageCaptures[0].state, 'preview');
  assert.equal(h.calls.some(u => u.endsWith('page-apply')), false);
});

test('lost apply receipt retries the identical capture id and payload', async () => {
  const h = await harness();
  await h.run("handlePageCapture({type:'capture-current',tabId:1,model:'25G64'})");
  const id = h.storage.pageCaptures[0].capture_id;
  h.loseAck();
  await h.run(`handlePageCapture({type:'capture-apply',capture_id:'${id}',selected:[0,1],complete:true})`);
  assert.equal(h.storage.pageCaptures[0].state, 'applying');
  const frozen = structuredClone(h.storage.pageCaptures[0].applyPayload);
  assert.equal(frozen.capture_id, id);
  await assert.rejects(h.run(`handlePageCapture({type:'capture-refresh',capture_id:'${id}'})`));
  await h.run('flushPageCaptures()');
  assert.equal(h.receipts.size, 1);
  assert.equal(h.storage.pageCaptures.length, 0);
  assert.equal(h.storage.lastPageCapture.saved, 2);
});

test('CAPTCHA and foreign/retailer URLs cannot enter the queue', async () => {
  const h = await harness(); h.setChallenge(true);
  await assert.rejects(h.run("handlePageCapture({type:'capture-current',tabId:1,model:'25G64'})"));
  assert.equal(h.storage.pageCaptures, undefined);
  for (const url of ['https://varle.lt/p/25g64', 'https://www.salidzini.lv/out/1', 'https://salidzini.lv.evil/cena']) {
    assert.throws(() => h.run(`salidziniPage('${url}')`));
  }
  assert.throws(() => h.run("captureAppUrl('https://remote.test')"));
});

test('changed app address does not leak queued data to another instance', async () => {
  const h = await harness(); h.setOnline(false);
  await h.run("handlePageCapture({type:'capture-current',tabId:1,model:'25G64'})");
  const count = h.calls.length;
  h.setOnline(true); h.setApp('http://127.0.0.1:8155'); await h.run('flushPageCaptures()');
  assert.equal(h.calls.length, count);
  assert.equal(h.storage.pageCaptures.length, 1);
  assert.match(h.storage.pageCaptures[0].error, /address changed/);
});

test('conflict preserves the snapshot; only explicit refresh rebinds the preview', async () => {
  const h = await harness();
  await h.run("handlePageCapture({type:'capture-current',tabId:1,model:'25G64'})");
  const id = h.storage.pageCaptures[0].capture_id;
  h.setStatus(409);
  await h.run(`handlePageCapture({type:'capture-apply',capture_id:'${id}',selected:[0],complete:false})`);
  assert.equal(h.storage.pageCaptures[0].state, 'error');
  const count = h.calls.length;
  h.setStatus(200); await h.run('flushPageCaptures()');
  assert.equal(h.calls.length, count);
  await h.run(`handlePageCapture({type:'capture-refresh',capture_id:'${id}'})`);
  assert.equal(h.storage.pageCaptures[0].state, 'preview');
});

test('selection survives popup closure and queue size is bounded', async () => {
  const h = await harness();
  await h.run("handlePageCapture({type:'capture-current',tabId:1,model:'25G64'})");
  const id = h.storage.pageCaptures[0].capture_id;
  await h.run(`handlePageCapture({type:'capture-selection',capture_id:'${id}',selected:[1],complete:false})`);
  assert.deepEqual(h.storage.pageCaptures[0].selected, [1]);
  h.setOnline(false);
  for (let i = 0; i < 4; i++) await h.run("handlePageCapture({type:'capture-current',tabId:1,model:'25G64'})");
  await assert.rejects(h.run("handlePageCapture({type:'capture-current',tabId:1,model:'25G64'})"));
  assert.equal(h.storage.pageCaptures.length, 5);
});
