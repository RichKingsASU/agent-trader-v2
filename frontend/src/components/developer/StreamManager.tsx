import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { useDataStreams, StreamType } from '@/contexts/DataStreamContext';
import { useExchanges } from '@/contexts/ExchangeContext';
import { Plus, Radio, Wifi, Globe } from 'lucide-react';
import { toast } from 'sonner';

// Common WebSocket endpoints for reference
const PRESET_ENDPOINTS: Record<string, { url: string; description: string }> = {
  'polygon-stocks': { url: 'wss://socket.polygon.io/stocks', description: 'Polygon.io Stocks' },
  'polygon-options': { url: 'wss://socket.polygon.io/options', description: 'Polygon.io Options' },
  'binance-spot': { url: 'wss://stream.binance.com:9443/ws', description: 'Binance Spot' },
  'coinbase': { url: 'wss://ws-feed.exchange.coinbase.com', description: 'Coinbase Pro' },
  'alpaca-iex': { url: 'wss://stream.data.alpaca.markets/v2/iex', description: 'Alpaca IEX' },
  'finnhub': { url: 'wss://ws.finnhub.io', description: 'Finnhub' },
};

export const StreamManager = () => {
  const { registerStream, connectRealStream } = useDataStreams();
  const { exchanges } = useExchanges();
  const [isOpen, setIsOpen] = useState(false);
  const [streamType, setStreamType] = useState<StreamType>('price');
  const [exchange, setExchange] = useState('');
  const [symbols, setSymbols] = useState('');
  const [isRealConnection, setIsRealConnection] = useState(false);
  const [wsUrl, setWsUrl] = useState('');
  const [selectedPreset, setSelectedPreset] = useState('');

  const activeExchanges = exchanges.filter(e => e.status === 'active' || e.status === 'degraded');

  const handlePresetChange = (preset: string) => {
    setSelectedPreset(preset);
    if (preset && PRESET_ENDPOINTS[preset]) {
      setWsUrl(PRESET_ENDPOINTS[preset].url);
    }
  };

  const handleAddStream = () => {
    if (!exchange || !symbols.trim()) {
      toast.error('Please fill in all fields');
      return;
    }

    if (isRealConnection && !wsUrl.trim()) {
      toast.error('Please enter a WebSocket URL');
      return;
    }

    const symbolList = symbols.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
    if (symbolList.length === 0) {
      toast.error('Please enter at least one symbol');
      return;
    }

    const streamNames: Record<StreamType, string> = {
      price: 'Price Stream',
      options: 'Options Flow',
      news: 'News Feed',
      level2: 'Level 2 Depth',
      trades: 'Trades Feed',
      account: 'Account Updates'
    };

    const streamId = `${streamType}-${exchange}-${Date.now()}`;

    // Register the stream first
    registerStream({
      id: streamId,
      name: streamNames[streamType],
      type: streamType,
      exchange,
      symbols: symbolList,
      status: isRealConnection ? 'connecting' : 'connecting',
      lastMessage: null,
      latencyMs: 0,
      lastError: null,
      connectedAt: null,
      url: isRealConnection ? wsUrl : undefined,
      isReal: isRealConnection
    });

    // If real connection, connect via WebSocket manager
    if (isRealConnection) {
      connectRealStream(streamId, wsUrl, symbolList);
      toast.success('Connecting to WebSocket...', {
        description: `${streamNames[streamType]} → ${wsUrl}`
      });
    } else {
      // Mock connection - simulate connecting then connected
      setTimeout(() => {
        // The stream will auto-update via the mock data simulation
      }, 1500);
      toast.success('Mock stream added', {
        description: `${streamNames[streamType]} for ${symbolList.join(', ')}`
      });
    }

    setIsOpen(false);
    setSymbols('');
    setWsUrl('');
    setSelectedPreset('');
    setIsRealConnection(false);
  };

  if (!isOpen) {
    return (
      <Button onClick={() => setIsOpen(true)} className="w-full">
        <Plus className="h-4 w-4 mr-2" />
        Add New Stream
      </Button>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Radio className="h-4 w-4" />
          Add New Data Stream
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Real Connection Toggle */}
        <div className="flex items-center justify-between p-3 rounded-lg bg-muted/50 border">
          <div className="flex items-center gap-2">
            {isRealConnection ? <Wifi className="h-4 w-4 text-emerald-500" /> : <Globe className="h-4 w-4 text-muted-foreground" />}
            <div>
              <p className="text-sm font-medium">{isRealConnection ? 'Real WebSocket' : 'Mock Data'}</p>
              <p className="text-xs text-muted-foreground">
                {isRealConnection ? 'Connect to live data feed' : 'Simulated data for testing'}
              </p>
            </div>
          </div>
          <Switch checked={isRealConnection} onCheckedChange={setIsRealConnection} />
        </div>

        {/* WebSocket URL (only shown for real connections) */}
        {isRealConnection && (
          <div className="space-y-3 p-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5">
            <div className="space-y-2">
              <Label>Preset Endpoints</Label>
              <Select value={selectedPreset} onValueChange={handlePresetChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a preset..." />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(PRESET_ENDPOINTS).map(([key, { description }]) => (
                    <SelectItem key={key} value={key}>
                      {description}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>WebSocket URL</Label>
              <Input 
                placeholder="wss://api.example.com/ws" 
                value={wsUrl}
                onChange={(e) => setWsUrl(e.target.value)}
                className="font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Enter the full WebSocket endpoint URL
              </p>
            </div>
          </div>
        )}

        <div className="space-y-2">
          <Label>Stream Type</Label>
          <Select value={streamType} onValueChange={(v) => setStreamType(v as StreamType)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="price">Price Stream</SelectItem>
              <SelectItem value="options">Options Flow</SelectItem>
              <SelectItem value="level2">Level 2 Depth</SelectItem>
              <SelectItem value="trades">Trades Feed</SelectItem>
              <SelectItem value="news">News Feed</SelectItem>
              <SelectItem value="account">Account Updates</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label>Exchange</Label>
          <Select value={exchange} onValueChange={setExchange}>
            <SelectTrigger>
              <SelectValue placeholder="Select exchange..." />
            </SelectTrigger>
            <SelectContent>
              {activeExchanges.map(ex => (
                <SelectItem key={ex.id} value={ex.id}>
                  {ex.displayName}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label>Symbols</Label>
          <Input 
            placeholder="SPY, AAPL, TSLA" 
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">Comma-separated list of symbols</p>
        </div>

        <div className="flex gap-2 pt-2">
          <Button variant="outline" onClick={() => setIsOpen(false)} className="flex-1">
            Cancel
          </Button>
          <Button onClick={handleAddStream} className="flex-1">
            {isRealConnection ? (
              <>
                <Wifi className="h-4 w-4 mr-2" />
                Connect Live
              </>
            ) : (
              'Add Mock Stream'
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};
