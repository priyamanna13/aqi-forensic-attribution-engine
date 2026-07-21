/**
 * AeroTrace AI — Real-time WebSocket Client
 * Fixed: URL corrected to port 8000 (FastAPI/Uvicorn).
 * The WS only handles SPIKE_ALERT toast notifications;
 * main dashboard data comes from REST API calls, not WS.
 */
export class WebSocketClient {
  constructor(url = "ws://localhost:8000/api/v1/simulation/ws") {
    this.url = url;
    this.socket = null;
    this.reconnectTimer = null;
    this.onMessageCallback = null;
    this.shouldReconnect = false;
  }

  connect(onMessageReceived) {
    this.onMessageCallback = onMessageReceived;
    this.shouldReconnect = true;
    this._establishConnection();
  }

  _establishConnection() {
    if (this.socket) this.disconnect();

    console.log(`[WS] Connecting to: ${this.url}`);
    try {
      this.socket = new WebSocket(this.url);

      this.socket.onopen = () => {
        console.log('[WS] Connection established.');
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
      };

      this.socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (this.onMessageCallback) this.onMessageCallback(data);
        } catch (err) {
          console.error('[WS] Failed to parse message JSON:', err);
        }
      };

      this.socket.onerror = (error) => {
        // Suppress noisy error objects — connection failures are normal when backend isn't running
        console.warn('[WS] Connection error (backend may be offline).');
      };

      this.socket.onclose = (event) => {
        console.log(`[WS] Closed. Code: ${event.code}`);
        this.socket = null;
        if (this.shouldReconnect) this._scheduleReconnect();
      };
    } catch (err) {
      console.error('[WS] Initialization error:', err);
      if (this.shouldReconnect) this._scheduleReconnect();
    }
  }

  _scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.shouldReconnect) this._establishConnection();
    }, 5000);
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.onopen = null;
      this.socket.onmessage = null;
      this.socket.onerror = null;
      this.socket.onclose = null;
      const sock = this.socket;
      this.socket = null;
      setTimeout(() => {
        try { sock.close(); } catch (_) {}
      }, 0);
    }
  }
}
