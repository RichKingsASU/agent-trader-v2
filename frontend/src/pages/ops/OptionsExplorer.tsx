import { useOptionsSnapshots } from '@/hooks/useOptionsSnapshots';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { RefreshCw, Filter, TrendingUp, TrendingDown } from 'lucide-react';
import { formatDistanceToNow, format } from 'date-fns';

const SYMBOLS = ['SPY', 'QQQ', 'IWM', 'AAPL', 'TSLA', 'NVDA'];
const TIME_WINDOWS = [
  { value: 15, label: 'Last 15 min' },
  { value: 30, label: 'Last 30 min' },
  { value: 60, label: 'Last 1 hour' },
  { value: 120, label: 'Last 2 hours' },
  { value: 240, label: 'Last 4 hours' },
];

export default function OptionsExplorer() {
  const { 
    snapshots, 
    filters, 
    updateFilters, 
    loading, 
    error, 
    totalCount,
    availableExpirations,
    refresh 
  } = useOptionsSnapshots();

  return (
    <div className="flex flex-col h-full p-6 space-y-6 overflow-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Options Snapshots Explorer</h1>
          <p className="text-sm text-muted-foreground">
            Browse alpaca_option_snapshots data
          </p>
        </div>
        <Button onClick={refresh} disabled={loading} variant="outline" size="sm">
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Filter className="h-4 w-4" />
            Filters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
            <div className="space-y-2">
              <Label>Symbol</Label>
              <Select
                value={filters.symbol}
                onValueChange={(value) => updateFilters({ symbol: value })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SYMBOLS.map(sym => (
                    <SelectItem key={sym} value={sym}>{sym}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Type</Label>
              <Select
                value={filters.optionType}
                onValueChange={(value: 'all' | 'call' | 'put') => updateFilters({ optionType: value })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="call">Calls</SelectItem>
                  <SelectItem value="put">Puts</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Strike Min</Label>
              <Input
                type="number"
                placeholder="Min"
                value={filters.strikeMin || ''}
                onChange={(e) => updateFilters({ strikeMin: e.target.value ? Number(e.target.value) : null })}
              />
            </div>

            <div className="space-y-2">
              <Label>Strike Max</Label>
              <Input
                type="number"
                placeholder="Max"
                value={filters.strikeMax || ''}
                onChange={(e) => updateFilters({ strikeMax: e.target.value ? Number(e.target.value) : null })}
              />
            </div>

            <div className="space-y-2">
              <Label>Expiration</Label>
              <Select
                value={filters.expiration || 'all'}
                onValueChange={(value) => updateFilters({ expiration: value === 'all' ? null : value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="All" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  {availableExpirations.map(exp => (
                    <SelectItem key={exp} value={exp}>{exp}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Time Window</Label>
              <Select
                value={String(filters.timeWindowMinutes)}
                onValueChange={(value) => updateFilters({ timeWindowMinutes: Number(value) })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TIME_WINDOWS.map(tw => (
                    <SelectItem key={tw.value} value={String(tw.value)}>{tw.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      <Card className="flex-1">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">
              Results
            </CardTitle>
            <Badge variant="secondary" className="number-mono">
              {snapshots.length} / {totalCount} rows
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="text-center py-8 text-[hsl(var(--bear))]">
              Error: {error}
            </div>
          ) : loading ? (
            <div className="text-center py-8 text-muted-foreground">
              Loading...
            </div>
          ) : snapshots.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No snapshots found for the selected filters
            </div>
          ) : (
            <div className="overflow-auto max-h-[600px]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Strike</TableHead>
                    <TableHead>Expiration</TableHead>
                    <TableHead className="text-right">Bid</TableHead>
                    <TableHead className="text-right">Ask</TableHead>
                    <TableHead className="text-right">Last</TableHead>
                    <TableHead className="text-right">IV</TableHead>
                    <TableHead className="text-right">Delta</TableHead>
                    <TableHead>Snapshot Time</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {snapshots.map((snap, idx) => (
                    <TableRow key={`${snap.option_symbol}-${idx}`}>
                      <TableCell className="font-medium number-mono">{snap.option_symbol}</TableCell>
                      <TableCell>
                        {snap.payload?.option_type === 'call' ? (
                          <Badge className="bg-[hsl(var(--bull))] text-[hsl(var(--bull-foreground))]">
                            <TrendingUp className="h-3 w-3 mr-1" />
                            CALL
                          </Badge>
                        ) : snap.payload?.option_type === 'put' ? (
                          <Badge className="bg-[hsl(var(--bear))] text-[hsl(var(--bear-foreground))]">
                            <TrendingDown className="h-3 w-3 mr-1" />
                            PUT
                          </Badge>
                        ) : (
                          <Badge variant="secondary">-</Badge>
                        )}
                      </TableCell>
                      <TableCell className="number-mono">${snap.payload?.strike?.toFixed(2) || '-'}</TableCell>
                      <TableCell className="number-mono">{snap.payload?.expiration || '-'}</TableCell>
                      <TableCell className="text-right number-mono">${snap.payload?.bid?.toFixed(2) || '-'}</TableCell>
                      <TableCell className="text-right number-mono">${snap.payload?.ask?.toFixed(2) || '-'}</TableCell>
                      <TableCell className="text-right number-mono">${snap.payload?.last?.toFixed(2) || '-'}</TableCell>
                      <TableCell className="text-right number-mono">{snap.payload?.iv ? `${(snap.payload.iv * 100).toFixed(1)}%` : '-'}</TableCell>
                      <TableCell className="text-right number-mono">{snap.payload?.delta?.toFixed(3) || '-'}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {format(new Date(snap.snapshot_time), 'HH:mm:ss')}
                        <br />
                        <span className="text-xs">{formatDistanceToNow(new Date(snap.snapshot_time), { addSuffix: true })}</span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
