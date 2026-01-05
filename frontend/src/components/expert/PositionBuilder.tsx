import { useState, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Plus, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

interface EntryLevel {
  id: string;
  price: number;
  size: number;
}

export function PositionBuilder() {
  const [entries, setEntries] = useState<EntryLevel[]>([
    { id: '1', price: 0, size: 0 }
  ]);

  const addEntry = () => {
    setEntries([...entries, { id: Date.now().toString(), price: 0, size: 0 }]);
  };

  const removeEntry = (id: string) => {
    if (entries.length > 1) {
      setEntries(entries.filter(e => e.id !== id));
    }
  };

  const updateEntry = (id: string, field: 'price' | 'size', value: number) => {
    setEntries(entries.map(e => e.id === id ? { ...e, [field]: value } : e));
  };

  const positionMetrics = useMemo(() => {
    const validEntries = entries.filter(e => e.price > 0 && e.size > 0);
    
    if (validEntries.length === 0) {
      return {
        totalSize: 0,
        weightedAvgPrice: 0,
        totalCost: 0,
        breakdown: []
      };
    }

    const totalSize = validEntries.reduce((sum, e) => sum + e.size, 0);
    const totalCost = validEntries.reduce((sum, e) => sum + (e.price * e.size), 0);
    const weightedAvgPrice = totalCost / totalSize;

    const breakdown = validEntries.map(e => ({
      ...e,
      cost: e.price * e.size,
      percentage: (e.size / totalSize) * 100
    }));

    return {
      totalSize,
      weightedAvgPrice,
      totalCost,
      breakdown
    };
  }, [entries]);

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle>Position Builder</CardTitle>
        <CardDescription>
          Combine multiple entries at different price levels with weighted average calculations
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Entry Levels */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <Label>Entry Levels</Label>
            <Button onClick={addEntry} size="sm" variant="outline">
              <Plus className="h-4 w-4 mr-1" />
              Add Entry
            </Button>
          </div>

          {entries.map((entry, index) => (
            <div key={entry.id} className="flex gap-2 items-end">
              <div className="flex-1">
                <Label className="text-xs">Entry {index + 1} Price</Label>
                <Input
                  type="number"
                  value={entry.price || ''}
                  onChange={(e) => updateEntry(entry.id, 'price', parseFloat(e.target.value) || 0)}
                  placeholder="0.00"
                  step="0.01"
                />
              </div>
              <div className="flex-1">
                <Label className="text-xs">Size (shares)</Label>
                <Input
                  type="number"
                  value={entry.size || ''}
                  onChange={(e) => updateEntry(entry.id, 'size', parseFloat(e.target.value) || 0)}
                  placeholder="0"
                  step="1"
                />
              </div>
              <Button
                onClick={() => removeEntry(entry.id)}
                size="icon"
                variant="ghost"
                disabled={entries.length === 1}
                className="shrink-0"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>

        {/* Position Summary */}
        {positionMetrics.totalSize > 0 && (
          <>
            <div className="pt-4 border-t space-y-3">
              <h4 className="font-medium">Position Summary</h4>
              
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Weighted Avg Entry</Label>
                  <div className="text-2xl font-bold">
                    ${positionMetrics.weightedAvgPrice.toFixed(2)}
                  </div>
                </div>
                
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Total Size</Label>
                  <div className="text-2xl font-bold">
                    {positionMetrics.totalSize.toLocaleString()}
                  </div>
                </div>
                
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Total Cost</Label>
                  <div className="text-xl font-semibold">
                    ${positionMetrics.totalCost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                </div>
                
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Number of Entries</Label>
                  <div className="text-xl font-semibold">
                    {positionMetrics.breakdown.length}
                  </div>
                </div>
              </div>
            </div>

            {/* Entry Breakdown */}
            <div className="space-y-2">
              <h4 className="font-medium text-sm">Entry Breakdown</h4>
              <div className="space-y-2">
                {positionMetrics.breakdown.map((entry, index) => (
                  <div key={entry.id} className="flex items-center justify-between p-3 rounded-lg bg-muted/50">
                    <div className="flex items-center gap-3">
                      <Badge variant="outline">E{index + 1}</Badge>
                      <div>
                        <div className="text-sm font-medium">
                          {entry.size} shares @ ${entry.price.toFixed(2)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Cost: ${entry.cost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </div>
                      </div>
                    </div>
                    <Badge variant="secondary">
                      {entry.percentage.toFixed(1)}%
                    </Badge>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
