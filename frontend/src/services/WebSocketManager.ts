// WebSocket Manager for handling multiple real-time data connections

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

export interface WebSocketConfig {
  url: string;
  protocols?: string[];
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
  heartbeatInterval?: number;
}

export interface WebSocketConnection {
  id: string;
  config: WebSocketConfig;
  socket: WebSocket | null;
  status: WebSocketStatus;
  reconnectAttempts: number;
  lastMessage: Date | null;
  messageCount: number;
  latencyMs: number;
}

type MessageHandler = (data: any, latencyMs: number) => void;
type StatusHandler = (status: WebSocketStatus, error?: string) => void;

class WebSocketManager {
  private connections: Map<string, WebSocketConnection> = new Map();
  private messageHandlers: Map<string, MessageHandler[]> = new Map();
  private statusHandlers: Map<string, StatusHandler[]> = new Map();
  private heartbeatIntervals: Map<string, NodeJS.Timeout> = new Map();
  private reconnectTimeouts: Map<string, NodeJS.Timeout> = new Map();

  connect(id: string, config: WebSocketConfig): void {
    // Clean up existing connection if present
    this.disconnect(id);

    const connection: WebSocketConnection = {
      id,
      config: {
        reconnectInterval: 5000,
        maxReconnectAttempts: 10,
        heartbeatInterval: 30000,
        ...config
      },
      socket: null,
      status: 'connecting',
      reconnectAttempts: 0,
      lastMessage: null,
      messageCount: 0,
      latencyMs: 0
    };

    this.connections.set(id, connection);
    this.notifyStatusChange(id, 'connecting');
    this.createSocket(id);
  }

  private createSocket(id: string): void {
    const connection = this.connections.get(id);
    if (!connection) return;

    try {
      const socket = new WebSocket(connection.config.url, connection.config.protocols);
      connection.socket = socket;

      socket.onopen = () => {
        console.log(`[WebSocket ${id}] Connected to ${connection.config.url}`);
        connection.status = 'connected';
        connection.reconnectAttempts = 0;
        this.notifyStatusChange(id, 'connected');
        this.startHeartbeat(id);
      };

      socket.onmessage = (event) => {
        const receiveTime = performance.now();
        connection.lastMessage = new Date();
        connection.messageCount++;

        try {
          let data = event.data;
          let sendTime: number | undefined;

          // Try to parse as JSON and extract timestamp for latency calculation
          if (typeof data === 'string') {
            try {
              const parsed = JSON.parse(data);
              data = parsed;
              
              // Check for common timestamp fields
              if (parsed.timestamp) {
                sendTime = new Date(parsed.timestamp).getTime();
              } else if (parsed.t) {
                sendTime = parsed.t;
              } else if (parsed.time) {
                sendTime = new Date(parsed.time).getTime();
              }
            } catch {
              // Not JSON, use raw string
            }
          }

          // Calculate latency if we have a timestamp
          const latencyMs = sendTime ? Math.max(0, receiveTime - sendTime) : connection.latencyMs;
          connection.latencyMs = latencyMs;

          this.notifyMessage(id, data, latencyMs);
        } catch (error) {
          console.error(`[WebSocket ${id}] Error processing message:`, error);
        }
      };

      socket.onerror = (error) => {
        console.error(`[WebSocket ${id}] Error:`, error);
        connection.status = 'error';
        this.notifyStatusChange(id, 'error', 'WebSocket error occurred');
      };

      socket.onclose = (event) => {
        console.log(`[WebSocket ${id}] Closed: code=${event.code}, reason=${event.reason}`);
        connection.status = 'disconnected';
        this.stopHeartbeat(id);
        this.notifyStatusChange(id, 'disconnected', event.reason || undefined);
        
        // Attempt reconnection if not intentionally closed
        if (event.code !== 1000 && connection.reconnectAttempts < (connection.config.maxReconnectAttempts || 10)) {
          this.scheduleReconnect(id);
        }
      };

    } catch (error) {
      console.error(`[WebSocket ${id}] Failed to create socket:`, error);
      connection.status = 'error';
      this.notifyStatusChange(id, 'error', String(error));
    }
  }

  private scheduleReconnect(id: string): void {
    const connection = this.connections.get(id);
    if (!connection) return;

    const delay = connection.config.reconnectInterval || 5000;
    connection.reconnectAttempts++;
    
    console.log(`[WebSocket ${id}] Scheduling reconnect attempt ${connection.reconnectAttempts} in ${delay}ms`);
    
    const timeout = setTimeout(() => {
      this.notifyStatusChange(id, 'connecting');
      this.createSocket(id);
    }, delay);

    this.reconnectTimeouts.set(id, timeout);
  }

  private startHeartbeat(id: string): void {
    const connection = this.connections.get(id);
    if (!connection || !connection.config.heartbeatInterval) return;

    const interval = setInterval(() => {
      if (connection.socket?.readyState === WebSocket.OPEN) {
        try {
          connection.socket.send(JSON.stringify({ type: 'ping', timestamp: Date.now() }));
        } catch (error) {
          console.error(`[WebSocket ${id}] Heartbeat error:`, error);
        }
      }
    }, connection.config.heartbeatInterval);

    this.heartbeatIntervals.set(id, interval);
  }

  private stopHeartbeat(id: string): void {
    const interval = this.heartbeatIntervals.get(id);
    if (interval) {
      clearInterval(interval);
      this.heartbeatIntervals.delete(id);
    }
  }

  disconnect(id: string): void {
    const connection = this.connections.get(id);
    if (!connection) return;

    // Clear reconnect timeout
    const timeout = this.reconnectTimeouts.get(id);
    if (timeout) {
      clearTimeout(timeout);
      this.reconnectTimeouts.delete(id);
    }

    // Stop heartbeat
    this.stopHeartbeat(id);

    // Close socket
    if (connection.socket) {
      connection.socket.close(1000, 'Client disconnect');
      connection.socket = null;
    }

    this.connections.delete(id);
    this.messageHandlers.delete(id);
    this.statusHandlers.delete(id);
  }

  send(id: string, data: any): boolean {
    const connection = this.connections.get(id);
    if (!connection?.socket || connection.socket.readyState !== WebSocket.OPEN) {
      console.warn(`[WebSocket ${id}] Cannot send - not connected`);
      return false;
    }

    try {
      const message = typeof data === 'string' ? data : JSON.stringify(data);
      connection.socket.send(message);
      return true;
    } catch (error) {
      console.error(`[WebSocket ${id}] Send error:`, error);
      return false;
    }
  }

  subscribe(id: string, symbols: string[]): boolean {
    return this.send(id, { action: 'subscribe', symbols });
  }

  unsubscribe(id: string, symbols: string[]): boolean {
    return this.send(id, { action: 'unsubscribe', symbols });
  }

  onMessage(id: string, handler: MessageHandler): () => void {
    if (!this.messageHandlers.has(id)) {
      this.messageHandlers.set(id, []);
    }
    this.messageHandlers.get(id)!.push(handler);

    return () => {
      const handlers = this.messageHandlers.get(id);
      if (handlers) {
        const index = handlers.indexOf(handler);
        if (index > -1) handlers.splice(index, 1);
      }
    };
  }

  onStatusChange(id: string, handler: StatusHandler): () => void {
    if (!this.statusHandlers.has(id)) {
      this.statusHandlers.set(id, []);
    }
    this.statusHandlers.get(id)!.push(handler);

    return () => {
      const handlers = this.statusHandlers.get(id);
      if (handlers) {
        const index = handlers.indexOf(handler);
        if (index > -1) handlers.splice(index, 1);
      }
    };
  }

  private notifyMessage(id: string, data: any, latencyMs: number): void {
    const handlers = this.messageHandlers.get(id);
    if (handlers) {
      handlers.forEach(handler => handler(data, latencyMs));
    }
  }

  private notifyStatusChange(id: string, status: WebSocketStatus, error?: string): void {
    const handlers = this.statusHandlers.get(id);
    if (handlers) {
      handlers.forEach(handler => handler(status, error));
    }
  }

  getConnection(id: string): WebSocketConnection | undefined {
    return this.connections.get(id);
  }

  getAllConnections(): WebSocketConnection[] {
    return Array.from(this.connections.values());
  }

  reconnect(id: string): void {
    const connection = this.connections.get(id);
    if (!connection) return;

    connection.reconnectAttempts = 0;
    if (connection.socket) {
      connection.socket.close(1000, 'Reconnecting');
    }
    this.notifyStatusChange(id, 'connecting');
    this.createSocket(id);
  }

  pause(id: string): void {
    const connection = this.connections.get(id);
    if (connection?.socket) {
      // We can't actually pause a WebSocket, but we can stop processing messages
      // For now, just update status
      this.notifyStatusChange(id, 'disconnected');
    }
  }

  resume(id: string): void {
    this.reconnect(id);
  }

  disconnectAll(): void {
    for (const id of this.connections.keys()) {
      this.disconnect(id);
    }
  }
}

// Singleton instance
export const wsManager = new WebSocketManager();
export default wsManager;
