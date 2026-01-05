// Mock Alpaca Server for testing without real credentials
// Simulates the Alpaca WebSocket protocol locally

export interface MockTradeMessage {
  T: 't';
  S: string;
  i: number;
  x: string;
  p: number;
  s: number;
  c: string[];
  t: string;
  z: string;
}

export interface MockQuoteMessage {
  T: 'q';
  S: string;
  ax: string;
  ap: number;
  as: number;
  bx: string;
  bp: number;
  bs: number;
  c: string[];
  t: string;
  z: string;
}

type MessageCallback = (messages: any[]) => void;

// Base prices for common symbols
const BASE_PRICES: Record<string, number> = {
  'SPY': 595.50,
  'AAPL': 195.25,
  'MSFT': 425.80,
  'GOOGL': 175.40,
  'AMZN': 205.60,
  'TSLA': 275.30,
  'NVDA': 145.20,
  'QQQ': 515.75,
  'BTC/USD': 105000,
  'ETH/USD': 3850,
  'SOL/USD': 225,
  'DOGE/USD': 0.42,
};

class MockAlpacaServer {
  private isRunning = false;
  private messageCallback: MessageCallback | null = null;
  private tradeInterval: NodeJS.Timeout | null = null;
  private quoteInterval: NodeJS.Timeout | null = null;
  private subscribedSymbols: { trades: string[]; quotes: string[]; bars: string[] } = {
    trades: [],
    quotes: [],
    bars: []
  };
  private prices: Record<string, number> = {};
  private tradeId = 1;

  start(onMessage: MessageCallback): void {
    this.messageCallback = onMessage;
    this.isRunning = true;

    // Simulate connection message
    setTimeout(() => {
      this.emit([{ T: 'success', msg: 'connected' }]);
    }, 100);
  }

  authenticate(): void {
    // Always succeed in mock mode
    setTimeout(() => {
      this.emit([{ T: 'success', msg: 'authenticated' }]);
    }, 150);
  }

  subscribe(trades: string[] = [], quotes: string[] = [], bars: string[] = []): void {
    this.subscribedSymbols.trades = [...new Set([...this.subscribedSymbols.trades, ...trades])];
    this.subscribedSymbols.quotes = [...new Set([...this.subscribedSymbols.quotes, ...quotes])];
    this.subscribedSymbols.bars = [...new Set([...this.subscribedSymbols.bars, ...bars])];

    // Initialize prices for subscribed symbols
    [...trades, ...quotes, ...bars].forEach(symbol => {
      if (!this.prices[symbol]) {
        this.prices[symbol] = BASE_PRICES[symbol] || (100 + Math.random() * 100);
      }
    });

    // Emit subscription confirmation
    setTimeout(() => {
      this.emit([{
        T: 'subscription',
        trades: this.subscribedSymbols.trades,
        quotes: this.subscribedSymbols.quotes,
        bars: this.subscribedSymbols.bars
      }]);

      // Start generating data
      this.startDataGeneration();
    }, 100);
  }

  private startDataGeneration(): void {
    // Clear existing intervals
    this.stopDataGeneration();

    // Generate trades every 200-500ms
    if (this.subscribedSymbols.trades.length > 0) {
      this.tradeInterval = setInterval(() => {
        if (!this.isRunning) return;
        
        const symbol = this.subscribedSymbols.trades[
          Math.floor(Math.random() * this.subscribedSymbols.trades.length)
        ];
        
        this.generateTrade(symbol);
      }, 200 + Math.random() * 300);
    }

    // Generate quotes every 100-200ms
    if (this.subscribedSymbols.quotes.length > 0) {
      this.quoteInterval = setInterval(() => {
        if (!this.isRunning) return;
        
        const symbol = this.subscribedSymbols.quotes[
          Math.floor(Math.random() * this.subscribedSymbols.quotes.length)
        ];
        
        this.generateQuote(symbol);
      }, 100 + Math.random() * 100);
    }
  }

  private stopDataGeneration(): void {
    if (this.tradeInterval) {
      clearInterval(this.tradeInterval);
      this.tradeInterval = null;
    }
    if (this.quoteInterval) {
      clearInterval(this.quoteInterval);
      this.quoteInterval = null;
    }
  }

  private generateTrade(symbol: string): void {
    // Random walk the price
    const change = (Math.random() - 0.5) * 0.002 * this.prices[symbol];
    this.prices[symbol] = Math.max(0.01, this.prices[symbol] + change);

    const trade: MockTradeMessage = {
      T: 't',
      S: symbol,
      i: this.tradeId++,
      x: 'V', // IEX
      p: parseFloat(this.prices[symbol].toFixed(2)),
      s: Math.floor(Math.random() * 500) + 1,
      c: [],
      t: new Date().toISOString(),
      z: 'A'
    };

    this.emit([trade]);
  }

  private generateQuote(symbol: string): void {
    const price = this.prices[symbol];
    const spread = price * 0.0002; // 0.02% spread

    const quote: MockQuoteMessage = {
      T: 'q',
      S: symbol,
      ax: 'V',
      ap: parseFloat((price + spread).toFixed(2)),
      as: Math.floor(Math.random() * 1000) + 100,
      bx: 'V',
      bp: parseFloat((price - spread).toFixed(2)),
      bs: Math.floor(Math.random() * 1000) + 100,
      c: [],
      t: new Date().toISOString(),
      z: 'A'
    };

    this.emit([quote]);
  }

  private emit(messages: any[]): void {
    if (this.messageCallback && this.isRunning) {
      this.messageCallback(messages);
    }
  }

  stop(): void {
    this.isRunning = false;
    this.stopDataGeneration();
    this.messageCallback = null;
    this.subscribedSymbols = { trades: [], quotes: [], bars: [] };
    this.prices = {};
  }

  isActive(): boolean {
    return this.isRunning;
  }
}

export const mockAlpacaServer = new MockAlpacaServer();
export default mockAlpacaServer;
