const socketWorker = new Worker('socket-worker.js');

socketWorker.onmessage = event => {
  const message = event.data || {};
  void chrome.runtime.sendMessage({ target: 'service-worker', ...message }).catch(() => {});
};

chrome.runtime.onMessage.addListener(message => {
  if (message?.target !== 'offscreen') return false;
  if (message.type === 'configure') socketWorker.postMessage(message);
  return false;
});

void chrome.runtime.sendMessage({ target: 'service-worker', type: 'offscreen-ready' }).catch(() => {});
