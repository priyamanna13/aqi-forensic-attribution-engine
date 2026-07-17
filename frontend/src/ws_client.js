/**
 * ws_client.js — Production-grade WebSocket client for the AQI Live Intelligence Pipeline.
 *
 * Lifecycle safety:
 *  - Safety gate on disconnect() prevents "close before connection established" browser exceptions.
 *  - All event listeners are stripped before close() to eliminate ghost callbacks on unmounted components.
 *  - close() is deferred to a macro-task (setTimeout 0) so it never blocks React's synchronous
 *    render/unmount cycle, eliminating layout-thread exceptions during rapid component teardowns.
 *
 * Reconnection:
 *  - Automatic 5-second reconnect on unexpected close (non-1000 codes).
 *  - Exponential backoff is NOT used here intentionally — a flat 5s retry is predictable and
 *    deterministic for demo environments where network latency is controlled.
 */

const WS_URL = 'ws://localhost:5000/ws/live';
const RECONNECT_DELAY_MS = 5000;

export class AQIWebSocketClient {
  /**
   * @param {(payload: object) => void} onSpike  — called with parsed JSON on every spike broadcast.
   * @param {(error: Event) => void}    onError  — optional error callback.
   */
  constructor(onSpike, onError = null) {
    this.onSpike   = onSpike;
    this.onError   = onError;
    this.socket    = null;
    this._retryTimer = null;
    this._destroyed  = false;  // permanent kill flag, set by destroy()
  }

  // ─── PUBLIC API ────────────────────────────────────────────────────────────

  /** Open the WebSocket connection. Safe to call multiple times — no-ops if already OPEN. */
  connect() {
    if (this._destroyed) return;
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;  // already live — do nothing
    }
    this._openSocket();
  }

  /**
   * Gracefully tear down the current socket.
   *
   * Safety gate #1: If the socket is still CONNECTING, calling .close() synchronously
   * throws a "WebSocket is closed before the connection is established" exception in some
   * browser engines. We therefore defer the actual .close() to a macro-task (setTimeout 0).
   *
   * Safety gate #2: All event listeners are nulled out BEFORE the deferred close fires.
   * This ensures that a racing onclose / onerror callback from a previous socket instance
   * can never trigger a reconnect loop or call into a stale React component tree.
   */
  disconnect() {
    // Cancel any pending reconnect timer
    if (this._retryTimer) {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
    }

    if (!this.socket) return;

    // Strip all listeners immediately — no ghost callbacks after this point.
    this.socket.onopen    = null;
    this.socket.onmessage = null;
    this.socket.onerror   = null;
    this.socket.onclose   = null;

    const socketToClose = this.socket;
    this.socket = null;

    // CONNECTING sockets cannot be closed synchronously without throwing in some browsers.
    // Deferring to a macro-task (setTimeout 0) makes the close non-blocking and exception-safe.
    setTimeout(() => {
      try {
        if (socketToClose) socketToClose.close(1000, 'client_disconnect');
      } catch (e) {
        // Intentionally swallowed — the socket may already be in a terminal state.
      }
    }, 0);
  }

  /**
   * Permanently destroy this client. Prevents any future reconnect attempts.
   * Call this from a React useEffect cleanup to ensure the client is fully dead
   * after component unmount.
   */
  destroy() {
    this._destroyed = true;
    this.disconnect();
  }

  // ─── INTERNAL ──────────────────────────────────────────────────────────────

  _openSocket() {
    try {
      this.socket = new WebSocket(WS_URL);
    } catch (e) {
      console.warn('[AQIWebSocket] Failed to construct WebSocket:', e);
      this._scheduleReconnect();
      return;
    }

    this.socket.onopen = () => {
      console.info('[AQIWebSocket] Connected →', WS_URL);
    };

    this.socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        this.onSpike(payload);
      } catch (e) {
        console.warn('[AQIWebSocket] Failed to parse message:', event.data, e);
      }
    };

    this.socket.onerror = (event) => {
      console.warn('[AQIWebSocket] Error event:', event);
      if (this.onError) this.onError(event);
      // onerror is always followed by onclose in the browser — reconnect logic lives in onclose.
    };

    this.socket.onclose = (event) => {
      if (event.code === 1000) {
        // Clean intentional close — do NOT reconnect.
        console.info('[AQIWebSocket] Connection closed cleanly (1000).');
        return;
      }
      console.warn(`[AQIWebSocket] Connection dropped (code=${event.code}). Reconnecting in ${RECONNECT_DELAY_MS / 1000}s...`);
      this._scheduleReconnect();
    };
  }

  _scheduleReconnect() {
    if (this._destroyed) return;
    if (this._retryTimer) return;  // already scheduled
    this._retryTimer = setTimeout(() => {
      this._retryTimer = null;
      if (!this._destroyed) {
        console.info('[AQIWebSocket] Attempting reconnect...');
        this._openSocket();
      }
    }, RECONNECT_DELAY_MS);
  }
}

export default AQIWebSocketClient;
