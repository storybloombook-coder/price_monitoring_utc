const HEARTBEAT_MS = 20000;
const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000];
let appUrl = '';
let activeJobIds = [];
let socket = null;
let heartbeatTimer = null;
let reconnectTimer = null;
let reconnectAttempt = 0;

function websocketUrl(value) {
  const url = new URL(value);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = '/browser-bridge/ws';
  url.search = '?auto_salidzini=1&open_collect=1';
  url.hash = '';
  return url.toString();
}

function publish(connected, message) {
  postMessage({ type: 'socket-state', connected, message, updatedAt: Date.now() });
}

function send(message) {
  if (socket?.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify(message));
  return true;
}

function scheduleReconnect() {
  if (!appUrl || reconnectTimer) return;
  const delay = RECONNECT_DELAYS_MS[Math.min(reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)];
  reconnectAttempt += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function connect() {
  if (!appUrl || socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) return;
  const current = new WebSocket(websocketUrl(appUrl));
  socket = current;
  current.onopen = () => {
    reconnectAttempt = 0;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = setInterval(() => {
      send({ type: 'heartbeat', at: Date.now() });
      publish(true, 'Connected to PriceMonitor · stable live channel');
    }, HEARTBEAT_MS);
    send({ type: 'hello', active_job_ids: activeJobIds });
    publish(true, 'Connected to PriceMonitor · stable live channel');
  };
  current.onmessage = event => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === 'ping') {
      send({ type: 'heartbeat', at: Date.now() });
    } else if (message.type === 'job' && message.job) {
      postMessage({ type: 'job', job: message.job });
    }
  };
  current.onerror = () => current.close();
  current.onclose = () => {
    if (socket === current) socket = null;
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = null;
    publish(false, 'Reconnecting stable live channel…');
    scheduleReconnect();
  };
}

onmessage = event => {
  const message = event.data || {};
  if (message.type !== 'configure') return;
  const nextUrl = String(message.appUrl || '').replace(/\/$/, '');
  activeJobIds = Array.isArray(message.activeJobIds) ? message.activeJobIds : [];
  if (nextUrl !== appUrl) {
    appUrl = nextUrl;
    socket?.close();
  }
  connect();
};
