import { useNewsEvents } from '@/hooks/useNewsEvents';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { RefreshCw, Newspaper, ExternalLink, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { formatDistanceToNow, format } from 'date-fns';

const SOURCES = ['benzinga', 'alpaca', 'polygon', 'finnhub'];
const LIMITS = [50, 100, 200, 500];

function SentimentBadge({ sentiment }: { sentiment: string | null }) {
  if (!sentiment) return <Badge variant="secondary">-</Badge>;
  
  const lower = sentiment.toLowerCase();
  if (lower.includes('positive') || lower.includes('bullish')) {
    return (
      <Badge className="bg-[hsl(var(--bull))] text-[hsl(var(--bull-foreground))]">
        <TrendingUp className="h-3 w-3 mr-1" />
        {sentiment}
      </Badge>
    );
  }
  if (lower.includes('negative') || lower.includes('bearish')) {
    return (
      <Badge className="bg-[hsl(var(--bear))] text-[hsl(var(--bear-foreground))]">
        <TrendingDown className="h-3 w-3 mr-1" />
        {sentiment}
      </Badge>
    );
  }
  return (
    <Badge variant="secondary">
      <Minus className="h-3 w-3 mr-1" />
      {sentiment}
    </Badge>
  );
}

export default function NewsViewer() {
  const { events, filters, updateFilters, loading, error, refresh } = useNewsEvents();

  return (
    <div className="flex flex-col h-full p-6 space-y-6 overflow-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">News Events Viewer</h1>
          <p className="text-sm text-muted-foreground">
            Browse news_events table
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
            <Newspaper className="h-4 w-4" />
            Filters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="space-y-2">
              <Label>Source</Label>
              <Select
                value={filters.source || 'all'}
                onValueChange={(value) => updateFilters({ source: value === 'all' ? null : value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="All sources" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Sources</SelectItem>
                  {SOURCES.map(src => (
                    <SelectItem key={src} value={src}>{src}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Symbol</Label>
              <Input
                placeholder="e.g. AAPL"
                value={filters.symbol || ''}
                onChange={(e) => updateFilters({ symbol: e.target.value || null })}
              />
            </div>

            <div className="space-y-2">
              <Label>Limit</Label>
              <Select
                value={String(filters.limit)}
                onValueChange={(value) => updateFilters({ limit: Number(value) })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LIMITS.map(lim => (
                    <SelectItem key={lim} value={String(lim)}>{lim} rows</SelectItem>
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
              News Events
            </CardTitle>
            <Badge variant="secondary" className="number-mono">
              {events.length} rows
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
          ) : events.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No news events found
            </div>
          ) : (
            <div className="overflow-auto max-h-[600px]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[100px]">Source</TableHead>
                    <TableHead className="w-[80px]">Symbol</TableHead>
                    <TableHead>Headline</TableHead>
                    <TableHead className="w-[100px]">Sentiment</TableHead>
                    <TableHead className="w-[60px]">Imp.</TableHead>
                    <TableHead className="w-[120px]">Received</TableHead>
                    <TableHead className="w-[50px]">Link</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {events.map((event) => (
                    <TableRow key={event.id}>
                      <TableCell>
                        <Badge variant="outline">{event.source}</Badge>
                      </TableCell>
                      <TableCell className="font-medium number-mono">
                        {event.symbol || '-'}
                      </TableCell>
                      <TableCell className="max-w-[400px]">
                        <p className="truncate" title={event.headline}>
                          {event.headline}
                        </p>
                        {event.category && (
                          <span className="text-xs text-muted-foreground">{event.category}</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <SentimentBadge sentiment={event.sentiment} />
                      </TableCell>
                      <TableCell className="text-center number-mono">
                        {event.importance ?? '-'}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {format(new Date(event.received_at), 'HH:mm:ss')}
                        <br />
                        <span>{formatDistanceToNow(new Date(event.received_at), { addSuffix: true })}</span>
                      </TableCell>
                      <TableCell>
                        {event.url && (
                          <a
                            href={event.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary hover:text-primary/80"
                          >
                            <ExternalLink className="h-4 w-4" />
                          </a>
                        )}
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
