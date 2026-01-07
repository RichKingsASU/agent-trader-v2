// Alpaca Markets WebSocket Service
// Supports IEX (free), SIP (paid), and Crypto feeds

export type AlpacaFeedType = 'iex' | 'sip' | 'crypto' | 'test';

export interface AlpacaCredentials {
  apiKey: string;
  secretKey: string;
}

export interface AlpacaTrade {
  T: 't';
  S: string; // Symbol
  i: number; // Trade ID
  x: string; // Exchange
  p: number; // Price
  s: number; // Size
  c: string[]; // Conditions
  t: string; // Timestamp (RFC-3339)
  z: string; // Tape
}

export interface AlpacaQuote {
  T: 'q';
  S: string; // Symbol
  ax: string; // Ask exchange
  ap: number; // Ask price
  as: number; // Ask size
  bx: string; // Bid exchange
  bp: number; // Bid price
  bs: number; // Bid size
  c: string[]; // Conditions
  t: string; // Timestamp
  z: string; // Tape
}

export interface AlpacaBar {
  T: 'b';
  S: string; // Symbol
  o: number; // Open
  h: number; // High
  l: number; // Low
  c: number; // Close
  v: number; // Volume
  t: string; // Timestamp
  n: number; // Trade count
  vw: number; // VWAP
}

export interface AlpacaCryptoTrade {
  T: 't';
  S: string; // Symbol (e.g., BTC/USD)
  p: number; // Price
  s: number; // Size
  t: string; // Timestamp
  i: number; // Trade ID
  tks: string; // Taker side
}

export interface AlpacaCryptoQuote {
  T: 'q';
  S: string; // Symbol
  bp: number; // Bid price
  bs: number; // Bid size
  ap: number; // Ask price
  as: number; // Ask size
  t: string; // Timestamp
}

export type AlpacaMessage = AlpacaTrade | AlpacaQuote | AlpacaBar | AlpacaCryptoTrade | AlpacaCryptoQuote;

type MessageHandler = (message: AlpacaMessage) => void;
type Status =
  | 'connecting'
  | 'authenticating'
  | 'authenticated'
  | 'subscribed'
  | 'error'
  | 'disconnected';
type StatusHandler = (status: Status, error?: string) => void;

const ALPACA_ENDPOINTS: Record<AlpacaFeedType, string> = {
  iex: 'wss://stream.data.alpaca.markets/v2/iex',
  sip: 'wss://stream.data.alpaca.markets/v2/sip',
  crypto: 'wss://stream.data.alpaca.markets/v1beta3/crypto/us',
  test: 'wss://stream.data.alpaca.markets/v2/test',
};

interface AlpacaSubscription {
  trades?: string[];
  quotes?: string[];
  bars?: string[];
}

class AlpacaWebSocket {
  private socket: WebSocket | null = null;
  private credentials: AlpacaCredentials | null = null;
  private feedType: AlpacaFeedType = 'iex';
  private subscriptions: AlpacaSubscription = {};
  private messageHandlers: MessageHandler[] = [];
  private statusHandlers: StatusHandler[] = [];
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private isAuthenticated = false;
  private isMockMode = false;
  private mockServer: typeof import('./MockAlpacaServer').mockAlpacaServer | null = null;

  connect(credentials: AlpacaCredentials, feedType: AlpacaFeedType = 'iex'): void {
    this.credentials = credentials;
    this.feedType = feedType;
    this.reconnectAttempts = 0;
    this.isAuthenticated = false;

    this.createConnection();
  }

  private createConnection(): void {
    if (!this.credentials) return;

    const url = ALPACA_ENDPOINTS[this.feedType];
    this.notifyStatus('connecting');

    try {
      this.socket = new WebSocket(url);

      this.socket.onopen = () => {
        // eslint-disable-next-line no-console
        console.log('[Alpaca] Connected, authenticating...');
        this.notifyStatus('authenticating');
        this.authenticate();
      };

      this.socket.onmessage = (event) => {
        this.handleMessage(event.data);
      };

      this.socket.onerror = (error) => {
        // eslint-disable-next-line no-console
        console.error('[Alpaca] WebSocket error:', error);
        this.notifyStatus('error', 'WebSocket connection error');
      };

      this.socket.onclose = (event) => {
        // eslint-disable-next-line no-console
        console.log(`[Alpaca] Connection closed: ${event.code} ${event.reason}`);
        this.isAuthenticated = false;

        if (event.code !== 1000 && this.reconnectAttempts < this.maxReconnectAttempts) {
          this.scheduleReconnect();
        } else {
          this.notifyStatus('disconnected', event.reason || undefined);
        }
      };
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error('[Alpaca] Failed to create connection:', error);
      this.notifyStatus('error', String(error));
    }
  }

  private authenticate(): void {
    if (!this.socket || !this.credentials) return;

    const authMessage = {
      action: 'auth',
      key: this.credentials.apiKey,
      secret: this.credentials.secretKey,
    };

    this.socket.send(JSON.stringify(authMessage));
  }

  private handleMessage(data: string): void {
    try {
      const messages = JSON.parse(data);

      // Alpaca sends arrays of messages
      if (!Array.isArray(messages)) return;

      for (const msg of messages) {
        switch (msg.T) {
          case 'success':
            if (msg.msg === 'connected') {
              // eslint-disable-next-line no-console
              console.log('[Alpaca] Connected to stream');
            } else if (msg.msg === 'authenticated') {
              // eslint-disable-next-line no-console
              console.log('[Alpaca] Authenticated successfully');
              this.isAuthenticated = true;
              this.reconnectAttempts = 0;
              this.notifyStatus('authenticated');

              // Resubscribe if we have pending subscriptions
              if (Object.keys(this.subscriptions).length > 0) this.resubscribe();
            }
            break;

          case 'error':
            // eslint-disable-next-line no-console
            console.error('[Alpaca] Error:', msg.code, msg.msg);
            this.notifyStatus('error', `${msg.code}: ${msg.msg}`);
            break;

          case 'subscription':
            // eslint-disable-next-line no-console
            console.log('[Alpaca] Subscription confirmed:', msg);
            this.notifyStatus('subscribed');
            break;

          case 't': // Trade
          case 'q': // Quote
          case 'b': // Bar
            this.notifyMessage(msg as AlpacaMessage);
            break;

          default:
            // eslint-disable-next-line no-console
            console.log('[Alpaca] Unknown message type:', msg.T, msg);
        }
      }
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error('[Alpaca] Error parsing message:', error, data);
    }
  }

  subscribe(subscription: AlpacaSubscription): void {
    this.subscriptions = {
      trades: [...(this.subscriptions.trades || []), ...(subscription.trades || [])],
      quotes: [...(this.subscriptions.quotes || []), ...(subscription.quotes || [])],
      bars: [...(this.subscriptions.bars || []), ...(subscription.bars || [])],
    };

    // Remove duplicates
    this.subscriptions.trades = [...new Set(this.subscriptions.trades)];
    this.subscriptions.quotes = [...new Set(this.subscriptions.quotes)];
    this.subscriptions.bars = [...new Set(this.subscriptions.bars)];

    if (this.isAuthenticated && this.socket?.readyState === WebSocket.OPEN) {
      this.sendSubscription(subscription);
    }
  }

  private sendSubscription(subscription: AlpacaSubscription): void {
    if (!this.socket) return;

    const message: any = { action: 'subscribe' };

    if (subscription.trades?.length) message.trades = subscription.trades;
    if (subscription.quotes?.length) message.quotes = subscription.quotes;
    if (subscription.bars?.length) message.bars = subscription.bars;

    // eslint-disable-next-line no-console
    console.log('[Alpaca] Subscribing:', message);
    this.socket.send(JSON.stringify(message));
  }

  private resubscribe(): void {
    if (!this.socket || !this.isAuthenticated) return;

    const message: any = { action: 'subscribe' };

    if (this.subscriptions.trades?.length) message.trades = this.subscriptions.trades;
    if (this.subscriptions.quotes?.length) message.quotes = this.subscriptions.quotes;
    if (this.subscriptions.bars?.length) message.bars = this.subscriptions.bars;

    if (Object.keys(message).length > 1) {
      // eslint-disable-next-line no-console
      console.log('[Alpaca] Resubscribing:', message);
      this.socket.send(JSON.stringify(message));
    }
  }

  unsubscribe(subscription: AlpacaSubscription): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;

    const message: any = { action: 'unsubscribe' };

    if (subscription.trades?.length) {
      message.trades = subscription.trades;
      this.subscriptions.trades = this.subscriptions.trades?.filter((s) => !subscription.trades?.includes(s));
    }
    if (subscription.quotes?.length) {
      message.quotes = subscription.quotes;
      this.subscriptions.quotes = this.subscriptions.quotes?.filter((s) => !subscription.quotes?.includes(s));
    }
    if (subscription.bars?.length) {
      message.bars = subscription.bars;
      this.subscriptions.bars = this.subscriptions.bars?.filter((s) => !subscription.bars?.includes(s));
    }

    this.socket.send(JSON.stringify(message));
  }

  private scheduleReconnect(): void {
    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);

    // eslint-disable-next-line no-console
    console.log(`[Alpaca] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    this.notifyStatus('connecting');

    this.reconnectTimeout = setTimeout(() => {
      this.createConnection();
    }, delay);
  }

  disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.isMockMode && this.mockServer) {
      this.mockServer.stop();
      this.mockServer = null;
      this.isMockMode = false;
    }

    if (this.socket) {
      this.socket.close(1000, 'Client disconnect');
      this.socket = null;
    }

    this.isAuthenticated = false;
    this.subscriptions = {};
    this.notifyStatus('disconnected');
  }

  // Connect in mock/demo mode - no real credentials needed
  async connectMock(): Promise<void> {
    this.isMockMode = true;
    this.reconnectAttempts = 0;
    this.isAuthenticated = false;

    this.notifyStatus('connecting');

    const { mockAlpacaServer } = await import('./MockAlpacaServer');
    this.mockServer = mockAlpacaServer;

    this.mockServer.start((messages) => {
      this.handleMockMessages(messages);
    });

    setTimeout(() => {
      this.notifyStatus('authenticating');
      this.mockServer?.authenticate();
    }, 100);
  }

  private handleMockMessages(messages: any[]): void {
    for (const msg of messages) {
      switch (msg.T) {
        case 'success':
          if (msg.msg === 'connected') {
            // eslint-disable-next-line no-console
            console.log('[Alpaca Mock] Connected');
          } else if (msg.msg === 'authenticated') {
            // eslint-disable-next-line no-console
            console.log('[Alpaca Mock] Authenticated');
            this.isAuthenticated = true;
            this.notifyStatus('authenticated');

            if (Object.keys(this.subscriptions).length > 0) {
              this.mockServer?.subscribe(
                this.subscriptions.trades || [],
                this.subscriptions.quotes || [],
                this.subscriptions.bars || []
              );
            }
          }
          break;

        case 'subscription':
          // eslint-disable-next-line no-console
          console.log('[Alpaca Mock] Subscribed:', msg);
          this.notifyStatus('subscribed');
          break;

        case 't':
        case 'q':
        case 'b':
          this.notifyMessage(msg as AlpacaMessage);
          break;
      }
    }
  }

  subscribeMock(subscription: AlpacaSubscription): void {
    this.subscriptions = {
      trades: [...(this.subscriptions.trades || []), ...(subscription.trades || [])],
      quotes: [...(this.subscriptions.quotes || []), ...(subscription.quotes || [])],
      bars: [...(this.subscriptions.bars || []), ...(subscription.bars || [])],
    };

    this.subscriptions.trades = [...new Set(this.subscriptions.trades)];
    this.subscriptions.quotes = [...new Set(this.subscriptions.quotes)];
    this.subscriptions.bars = [...new Set(this.subscriptions.bars)];

    if (this.isMockMode && this.isAuthenticated && this.mockServer) {
      this.mockServer.subscribe(subscription.trades || [], subscription.quotes || [], subscription.bars || []);
    }
  }

  isMock(): boolean {
    return this.isMockMode;
  }

  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.push(handler);
    return () => {
      const index = this.messageHandlers.indexOf(handler);
      if (index > -1) this.messageHandlers.splice(index, 1);
    };
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.push(handler);
    return () => {
      const index = this.statusHandlers.indexOf(handler);
      if (index > -1) this.statusHandlers.splice(index, 1);
    };
  }

  private notifyMessage(message: AlpacaMessage): void {
    this.messageHandlers.forEach((h) => h(message));
  }

  private notifyStatus(status: Status, error?: string): void {
    this.statusHandlers.forEach((h) => h(status, error));
  }

  isConnected(): boolean {
    if (this.isMockMode) return this.isAuthenticated && (this.mockServer?.isActive() ?? false);
    return this.socket?.readyState === WebSocket.OPEN && this.isAuthenticated;
  }

  getSubscriptions(): AlpacaSubscription {
    return { ...this.subscriptions };
  }

  static getEndpoint(feedType: AlpacaFeedType): string {
    return ALPACA_ENDPOINTS[feedType];
  }
}

export const alpacaWs = new AlpacaWebSocket();
export default alpacaWs;

