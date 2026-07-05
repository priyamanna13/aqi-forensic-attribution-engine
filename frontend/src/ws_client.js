/**
 * AeroTrace AI — Real-time Simulation WebSocket Client
 * Phase 2: Live Ngrok WebSocket Integration with Auto-Reconnection
 */
export class WebSocketClient {
  constructor(url = "ws://localhost:5000/api/v1/simulation/ws") {
    this.url = url;
    this.socket = null;
    this.reconnectTimer = null;
    this.onMessageCallback = null;
    this.shouldReconnect = false;
  }

  /**
   * Connect to the WebSocket server and bind message receiver.
   * @param {Function} onMessageReceived - Callback invoked when a message arrives.
   */
  connect(onMessageReceived) {
    this.onMessageCallback = onMessageReceived;
    this.shouldReconnect = true;
    this._establishConnection();
  }

  /**
   * Internal connection establishing logic.
   */
  _establishConnection() {
    // Prevent multiple connections
    if (this.socket) {
      this.disconnect();
    }

    console.log(`🔌 Connecting to WebSocket: ${this.url}`);
    try {
      this.socket = new WebSocket(this.url);

      this.socket.onopen = () => {
        console.log("⚡ WebSocket connection established successfully.");
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
      };

      this.socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log("📥 WebSocket message received:", data);
          if (this.onMessageCallback) {
            this.onMessageCallback(data);
          }
        } catch (err) {
          console.error("❌ Failed to parse WebSocket message JSON:", err);
        }
      };

      this.socket.onerror = (error) => {
        console.error("❌ WebSocket error encountered:", error);
      };

      this.socket.onclose = (event) => {
        console.log(`🔌 WebSocket connection closed. Code: ${event.code}, Reason: ${event.reason}`);
        this.socket = null;
        if (this.shouldReconnect) {
          this._scheduleReconnect();
        }
      };
    } catch (err) {
      console.error("❌ Error during WebSocket initialization:", err);
      if (this.shouldReconnect) {
        this._scheduleReconnect();
      }
    }
  }

  /**
   * Schedules a reconnection attempt after 5 seconds.
   */
  _scheduleReconnect() {
    if (this.reconnectTimer) return;
    console.log("🔄 Scheduling WebSocket reconnect in 5000ms...");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.shouldReconnect) {
        this._establishConnection();
      }
    }, 5000);
  }

  /**
   * Manually disconnect the WebSocket connection and stop reconnect attempts.
   */
  disconnect() {
    console.log("🔌 Manually disconnecting WebSocket...");
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      // Clear event handlers before closing to prevent reconnect cycles
      this.socket.onopen = null;
      this.socket.onmessage = null;
      this.socket.onerror = null;
      this.socket.onclose = null;
      
      try {
        this.socket.close();
      } catch (err) {
        console.error("❌ Error closing socket:", err);
      }
      this.socket = null;
    }
  }
}
