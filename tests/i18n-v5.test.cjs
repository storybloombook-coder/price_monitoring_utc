const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {translateText, RU} = require('../src/price_monitor_v5/static/i18n.js');

test('English remains the source UI language', () => {
  assert.equal(translateText('Start monitoring', 'en'), 'Start monitoring');
  assert.equal(translateText('25G64', 'en'), '25G64');
});

test('Russian translates static controls, tooltips and confirmations', () => {
  assert.equal(translateText('Start monitoring', 'ru'), 'Начать мониторинг');
  assert.equal(translateText('Copy the model name to the clipboard', 'ru'), 'Скопировать название модели в буфер обмена');
  assert.equal(translateText('Remove this false match from the current run?', 'ru'), 'Удалить это ложное совпадение из текущего прогона?');
  assert.ok(Object.keys(RU).length > 150);
  assert.equal(translateText('How this marketplace is collected', 'ru'), 'Как происходит сбор информации');
  assert.match(translateText('Search TCL + model and read seller offers on the matching comparison page. One timeout is retried automatically. S45HE/S45H, S55HE/S55H and Q75HE/Q75H are explicit aliases; false prefix candidates are rejected and plausible variants go to Quick Review. Delivery time alone does not confirm stock. No retailer pages are opened.', 'ru'), /Поиск выполняется по TCL \+ модели/);
  assert.match(translateText('Salidzini Auto paused this batch to protect the browser session after CAPTCHA or repeated unavailable pages. No request was sent for this SKU. Complete the CAPTCHA in the retained tab, then retry Salidzini in a batch of 5.', 'ru'), /Запрос по этому SKU не отправлялся/);
});

test('Russian translates live counters without touching SKU and price data', () => {
  assert.equal(translateText('Monitoring: 7 active, 2 paused · Stock: 4 active, 1 unmatched', 'ru'), 'Мониторинг: 7 активно, 2 приостановлено · Склад: 4 активно, 1 не сопоставлено');
  assert.equal(translateText('Review required checks (3)', 'ru'), 'Проверить вручную (3)');
  assert.equal(translateText('Success 2', 'ru'), 'Успешно 2');
  assert.equal(translateText('0 models · v5 catalog · stock auto-enrolled', 'ru'), '0 моделей · каталог v5 · склад добавляется автоматически');
  assert.equal(translateText('· cache up to 4 hours', 'ru'), '· кеш до 4 часов');
  assert.equal(translateText('25G64', 'ru'), '25G64');
  assert.equal(translateText('199.00 EUR', 'ru'), '199.00 EUR');
});

test('Russian translates the engine-ready location requested for the toggle', () => {
  assert.equal(translateText('v5.0.20 · marketplace engine ready', 'ru'), 'v5.0.20 · движок маркетплейсов готов');
  assert.equal(translateText('v5: only Kaina24, Salidzini and Hinnavaatlus are queried. Shop columns are derived from marketplace offers.', 'ru'), 'v5: запрашиваются только Kaina24, Salidzini и Hinnavaatlus. Столбцы магазинов формируются из предложений маркетплейсов.');
});

test('HTML loads localization before application code and exposes both language buttons', () => {
  const html = fs.readFileSync(path.join(__dirname, '../src/price_monitor_v5/static/index.html'), 'utf8');
  assert.ok(html.indexOf('/assets/i18n.js?v=5.0.20') < html.indexOf('/assets/app.js?v=5.0.20'));
  assert.match(html, /data-language="en"/);
  assert.match(html, /data-language="ru"/);
  assert.match(html, /Price Monitor v5\.0\.20/);
  assert.equal(translateText('Retry pass 1 will not roll over to previously visited models.', 'ru'), 'Круг перепроверки 1 не перейдёт повторно к уже пройденным моделям.');
  const script = fs.readFileSync(path.join(__dirname, '../src/price_monitor_v5/static/i18n.js'), 'utf8');
  assert.match(script, /typeof window === 'undefined'/);
  assert.match(script, /searchParams\.set\('lang', next\)/);
});

test('live result refresh retries rendering and reconciles the table on tab return', () => {
  const script = fs.readFileSync(path.join(__dirname, '../src/price_monitor_v5/static/app.js'), 'utf8');
  const guardedRender = 'if (resultsChanged) { renderResults(); state.resultRenderSignature = resultSignature; }';
  assert.ok(script.includes(guardedRender));
  assert.doesNotMatch(script, /state\.resultRenderSignature = resultSignature;\s*if \(run\.cleared\)/);
  assert.match(script, /window\.addEventListener\('focus', refreshRunWhenVisible\)/);
  assert.match(script, /document\.addEventListener\('visibilitychange', refreshRunWhenVisible\)/);
  assert.match(script, /one background Salidzini tab and reuses it/);
  assert.doesNotMatch(script, /function coverageInfo\(/);
  assert.match(script, /Retry only marketplaces without a collected price/);
});

test('browser toggle persists the choice and navigates to an explicit language URL', () => {
  const script = fs.readFileSync(path.join(__dirname, '../src/price_monitor_v5/static/i18n.js'), 'utf8');
  const handlers = {}; const stored = {}; let assigned = '';
  const button = language => ({dataset:{language}, classList:{toggle(){}}, setAttribute(){}, addEventListener(type, handler){handlers[`${language}:${type}`] = handler;}});
  const buttons = [button('en'), button('ru')];
  const context = {
    window:{}, navigator:{language:'en-US'}, URL, URLSearchParams, WeakSet,
    localStorage:{getItem:key => stored[key], setItem:(key,value) => {stored[key] = value;}},
    location:{search:'?lang=ru', href:'http://127.0.0.1:8050/?lang=ru', assign:value => {assigned = value;}},
    document:{readyState:'complete', documentElement:{}, nodeType:9, querySelectorAll:selector => selector === '[data-language]' ? buttons : [], createTreeWalker:() => ({nextNode:() => null})},
    Node:{TEXT_NODE:3,ELEMENT_NODE:1,DOCUMENT_NODE:9}, NodeFilter:{SHOW_TEXT:4,SHOW_ELEMENT:1},
    MutationObserver:class { observe(){} }
  };
  vm.runInNewContext(script, context);
  assert.equal(context.window.pmI18n.language, 'ru');
  handlers['en:click']();
  assert.equal(stored['price-monitor-v5.language'], 'en');
  assert.match(assigned, /[?&]lang=en(?:&|$)/);
});
