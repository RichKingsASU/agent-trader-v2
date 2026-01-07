import { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  DollarSign,
  FlaskConical,
  Play,
  Shield,
  Square,
  TrendingUp,
  Zap,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import { useDataStreams } from '@/contexts/DataStreamContext';
import { useExchanges } from '@/contexts/ExchangeContext';
import { logEvent } from '@/lib/eventLogStore';
import { alpacaWs, type AlpacaFeedType, type AlpacaMessage } from '@/services/AlpacaWebSocket';

type ConnectionStatus = 'disconnected' | 'connecting' | 'authenticating' | 'authenticated' | 'subscribed' | 'error';

const FEED_OPTIONS: { value: AlpacaFeedType; label: string; description: string; free: boolean }[] = [
  { value: 'iex', label: 'IEX', description: 'Free delayed data (15-min)', free: true },
  { value: 'sip', label: 'SIP', description: 'Real-time consolidated feed', free: false },
  { value: 'crypto', label: 'Crypto', description: 'Real-time crypto data', free: true },
  { value: 'test', label: 'Test', description: 'Fake data for testing', free: true },
];

const PRESET_SYMBOLS = {
  stocks: ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'SPY', 'QQQ'],
  crypto: ['BTC/USD', 'ETH/USD', 'SOL/USD', 'DOGE/USD'],
};

export const AlpacaStreamManager = () => {
  const { registerStream, recordMessage, updateStreamStatus, unregisterStream } = useDataStreams();
  const { updateExchangeStatus } = useExchanges();

  const [isExpanded, setIsExpanded] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [secretKey, setSecretKey] = useState('');
  const [feedType, setFeedType] = useState<AlpacaFeedType>('iex');
  const [symbols, setSymbols] = useState('SPY, AAPL');
  const [subscribeTrades, setSubscribeTrades] = useState(true);
  const [subscribeQuotes, setSubscribeQuotes] = useState(false);
  const [subscribeBars, setSubscribeBars] = useState(false);

  const [status, setStatus] = useState<ConnectionStatus>('disconnected');
  const [lastError, setLastError] = useState<string | null>(null);
  const [messageCount, setMessageCount] = useState(0);
  const [lastPrice, setLastPrice] = useState<Record<string, number>>({});

  const msgCountRef = useRef(0);
  const firstMessageReceived = useRef(false);

  const streamId = 'alpaca-live';

  useEffect(() => {
    const unsubStatus = alpacaWs.onStatus((newStatus, error) => {
      setStatus(newStatus);
      if (error) setLastError(error);

      const symbolList = symbols
        .split(',')
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean);

      logEvent(error ? 'error' : 'info', 'alpaca', 'connection', `Alpaca ${newStatus}${error ? `: ${error}` : ''}`, {
        feedType,
        symbols: symbolList,
      });

      if (newStatus === 'authenticated' || newStatus === 'subscribed') {
        updateStreamStatus(streamId, 'connected');
        updateExchangeStatus('alpaca', 'active', { streams: [streamId], latencyMs: 25, errorRate: 0 });
      } else if (newStatus === 'connecting' || newStatus === 'authenticating') {
        updateStreamStatus(streamId, 'connecting');
      } else if (newStatus === 'error') {
        updateStreamStatus(streamId, 'error', error);
        updateExchangeStatus('alpaca', 'degraded', { errorRate: 0.5 });
      } else if (newStatus === 'disconnected') {
        updateStreamStatus(streamId, 'disconnected');
        updateExchangeStatus('alpaca', 'inactive', { streams: [], latencyMs: 0 });
      }
    });

    const unsubMessage = alpacaWs.onMessage((message: AlpacaMessage) => {
      setMessageCount((c) => c + 1);
      msgCountRef.current += 1;
      recordMessage(streamId);

      if (!firstMessageReceived.current) {
        firstMessageReceived.current = true;
        logEvent('info', 'alpaca', 'message', 'First message received', { type: message.T, symbol: message.S });
      }

      if (message.T === 't') setLastPrice((prev) => ({ ...prev, [message.S]: message.p }));

      if (msgCountRef.current % 25 === 0) {
        logEvent('debug', 'alpaca', 'message', `Received ${msgCountRef.current} messages`, {
          lastType: message.T,
          lastSymbol: message.S,
        });
      }
    });

    return () => {
      unsubStatus();
      unsubMessage();
    };
  }, [recordMessage, updateStreamStatus, updateExchangeStatus, symbols, feedType]);

  const handleConnect = async () => {
    const symbolList = symbols
      .split(',')
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    if (symbolList.length === 0) {
      toast.error('Please enter at least one symbol');
      return;
    }

    if (!demoMode && (!apiKey || !secretKey)) {
      toast.error('Please enter your Alpaca API credentials or enable Demo Mode');
      return;
    }

    logEvent('info', 'alpaca', 'ui', 'Connect clicked', { symbols: symbolList, feedType, demoMode });

    registerStream({
      id: streamId,
      name: demoMode ? 'Alpaca Demo' : 'Alpaca Live',
      type: 'price',
      exchange: 'alpaca',
      symbols: symbolList,
      status: 'connecting',
      lastMessage: null,
      latencyMs: 0,
      lastError: null,
      connectedAt: null,
      isReal: !demoMode,
      url: demoMode ? 'mock://alpaca-demo' : `wss://stream.data.alpaca.markets/v2/${feedType}`,
    });

    const buildSubscription = () => {
      const subscription: any = {};
      if (subscribeTrades) subscription.trades = symbolList;
      if (subscribeQuotes) subscription.quotes = symbolList;
      if (subscribeBars) subscription.bars = symbolList;
      return subscription;
    };

    if (demoMode) {
      await alpacaWs.connectMock();

      const checkAuth = setInterval(() => {
        if (!alpacaWs.isConnected()) return;
        clearInterval(checkAuth);

        const subscription = buildSubscription();
        logEvent('info', 'alpaca', 'subscription', 'Subscribe sent', {
          trades: subscribeTrades ? symbolList : [],
          quotes: subscribeQuotes ? symbolList : [],
          bars: subscribeBars ? symbolList : [],
        });

        alpacaWs.subscribeMock(subscription);
        toast.success('Demo Mode Connected', { description: `Streaming simulated data for ${symbolList.join(', ')}` });
      }, 100);

      setTimeout(() => clearInterval(checkAuth), 5000);
    } else {
      alpacaWs.connect({ apiKey, secretKey }, feedType);

      const checkAuth = setInterval(() => {
        if (!alpacaWs.isConnected()) return;
        clearInterval(checkAuth);

        const subscription = buildSubscription();
        logEvent('info', 'alpaca', 'subscription', 'Subscribe sent', {
          trades: subscribeTrades ? symbolList : [],
          quotes: subscribeQuotes ? symbolList : [],
          bars: subscribeBars ? symbolList : [],
        });

        alpacaWs.subscribe(subscription);
        toast.success('Connected to Alpaca', { description: `Subscribed to ${symbolList.join(', ')}` });
      }, 100);

      setTimeout(() => clearInterval(checkAuth), 10000);
    }
  };

  const handleDisconnect = () => {
    logEvent('info', 'alpaca', 'ui', 'Disconnect clicked');
    alpacaWs.disconnect();
    unregisterStream(streamId);
    setMessageCount(0);
    setLastPrice({});
    msgCountRef.current = 0;
    firstMessageReceived.current = false;
    toast.info('Disconnected from Alpaca');
  };

  const handleTestLog = () => {
    logEvent('info', 'alpaca', 'test', 'Alpaca log pipeline OK');
    toast.success('Test log emitted - check Debug Console');
  };

  const handleAddSymbols = (presetSymbols: string[]) => {
    const current = symbols.split(',').map((s) => s.trim()).filter(Boolean);
    const combined = [...new Set([...current, ...presetSymbols])];
    setSymbols(combined.join(', '));
  };

  const isConnected = status === 'authenticated' || status === 'subscribed';

  const getStatusColor = () => {
    switch (status) {
      case 'authenticated':
      case 'subscribed':
        return 'bg-emerald-500';
      case 'connecting':
      case 'authenticating':
        return 'bg-amber-500';
      case 'error':
        return 'bg-destructive';
      default:
        return 'bg-muted-foreground';
    }
  };

  const getStatusText = () => {
    switch (status) {
      case 'authenticated':
        return 'Authenticated';
      case 'subscribed':
        return 'Streaming';
      case 'connecting':
        return 'Connecting...';
      case 'authenticating':
        return 'Authenticating...';
      case 'error':
        return 'Error';
      default:
        return 'Disconnected';
    }
  };

  if (!isExpanded) {
    return (
      <Card className="border-2 border-dashed hover:border-primary/50 transition-colors cursor-pointer" onClick={() => setIsExpanded(true)}>
        <CardContent className="flex items-center justify-between p-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-amber-500/10 flex items-center justify-center">
              <span className="text-xl">🦙</span>
            </div>
            <div>
              <h3 className="font-medium">Alpaca Markets</h3>
              <p className="text-sm text-muted-foreground">Free real-time stock & crypto data</p>
            </div>
          </div>
          <Badge variant="outline" className="text-amber-600 border-amber-600/50">
            Free Tier
          </Badge>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-amber-500/30">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-amber-500/10 flex items-center justify-center">
              <span className="text-xl">🦙</span>
            </div>
            <div>
              <CardTitle className="text-base">Alpaca Markets</CardTitle>
              <p className="text-xs text-muted-foreground">WebSocket Streaming</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" className="text-xs h-7 px-2" onClick={handleTestLog}>
              <FlaskConical className="h-3 w-3 mr-1" />
              Test Log
            </Button>
            <span className={`h-2.5 w-2.5 rounded-full ${getStatusColor()} animate-pulse`} />
            <span className="text-sm">{getStatusText()}</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between p-3 rounded-lg bg-primary/5 border border-primary/20">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-primary" />
            <div>
              <Label htmlFor="demo-mode" className="font-medium cursor-pointer">
                Demo Mode
              </Label>
              <p className="text-xs text-muted-foreground">Use simulated data - no credentials needed</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {demoMode && <Badge className="bg-primary text-primary-foreground">DEMO</Badge>}
            <Switch id="demo-mode" checked={demoMode} onCheckedChange={setDemoMode} disabled={isConnected} />
          </div>
        </div>

        {!demoMode && (
          <div className="space-y-3 p-3 rounded-lg bg-muted/30 border">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Shield className="h-4 w-4" />
              API Credentials
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label className="text-xs">API Key ID</Label>
                <Input
                  type="password"
                  placeholder="PKXXXXXXXXXXXXXXXX"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  disabled={isConnected}
                  className="font-mono text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Secret Key</Label>
                <Input
                  type="password"
                  placeholder="••••••••••••••••"
                  value={secretKey}
                  onChange={(e) => setSecretKey(e.target.value)}
                  disabled={isConnected}
                  className="font-mono text-sm"
                />
              </div>
            </div>

            <p className="text-xs text-muted-foreground flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" />
              Keys are stored in memory only. Get free keys at{' '}
              <a href="https://alpaca.markets" target="_blank" rel="noopener noreferrer" className="underline">
                alpaca.markets
              </a>
            </p>
          </div>
        )}

        {!demoMode && (
          <div className="space-y-2">
            <Label>Data Feed</Label>
            <Select value={feedType} onValueChange={(v) => setFeedType(v as AlpacaFeedType)} disabled={isConnected}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FEED_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    <div className="flex items-center gap-2">
                      <span>{opt.label}</span>
                      {opt.free && (
                        <Badge variant="secondary" className="text-xs py-0">
                          Free
                        </Badge>
                      )}
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{FEED_OPTIONS.find((f) => f.value === feedType)?.description}</p>
          </div>
        )}

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Symbols</Label>
            <div className="flex gap-1">
              <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => handleAddSymbols(PRESET_SYMBOLS.stocks)}>
                + Stocks
              </Button>
              {feedType === 'crypto' && (
                <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => handleAddSymbols(PRESET_SYMBOLS.crypto)}>
                  + Crypto
                </Button>
              )}
            </div>
          </div>
          <Input
            placeholder={feedType === 'crypto' ? 'BTC/USD, ETH/USD' : 'SPY, AAPL, TSLA'}
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
            disabled={isConnected}
          />
        </div>

        <div className="space-y-3">
          <Label>Subscribe To</Label>
          <div className="flex flex-wrap gap-4">
            <div className="flex items-center gap-2">
              <Switch id="trades" checked={subscribeTrades} onCheckedChange={setSubscribeTrades} disabled={isConnected} />
              <Label htmlFor="trades" className="flex items-center gap-1.5 cursor-pointer">
                <TrendingUp className="h-3.5 w-3.5" />
                Trades
              </Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch id="quotes" checked={subscribeQuotes} onCheckedChange={setSubscribeQuotes} disabled={isConnected} />
              <Label htmlFor="quotes" className="flex items-center gap-1.5 cursor-pointer">
                <DollarSign className="h-3.5 w-3.5" />
                Quotes
              </Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch id="bars" checked={subscribeBars} onCheckedChange={setSubscribeBars} disabled={isConnected} />
              <Label htmlFor="bars" className="flex items-center gap-1.5 cursor-pointer">
                <BarChart3 className="h-3.5 w-3.5" />
                Bars
              </Label>
            </div>
          </div>
        </div>

        <Separator />

        {isConnected && (
          <div className="grid grid-cols-3 gap-3 p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
            <div className="text-center">
              <p className="text-2xl font-bold text-emerald-600">{messageCount.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">Messages</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold">{Object.keys(lastPrice).length}</p>
              <p className="text-xs text-muted-foreground">Active Symbols</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-amber-600">{Object.entries(lastPrice)[0]?.[1]?.toFixed(2) || '—'}</p>
              <p className="text-xs text-muted-foreground">{Object.entries(lastPrice)[0]?.[0] || 'Last Price'}</p>
            </div>
          </div>
        )}

        {lastError && <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/30 text-sm text-destructive">{lastError}</div>}

        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setIsExpanded(false)} className="flex-1">
            Collapse
          </Button>
          {isConnected ? (
            <Button variant="destructive" onClick={handleDisconnect} className="flex-1">
              <Square className="h-4 w-4 mr-2" />
              Disconnect
            </Button>
          ) : (
            <Button onClick={handleConnect} className="flex-1 bg-amber-600 hover:bg-amber-700">
              <Play className="h-4 w-4 mr-2" />
              Connect
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
};

