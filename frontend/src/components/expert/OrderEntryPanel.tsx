import { useState, useEffect } from 'react';
import { Send, TrendingUp, TrendingDown, AlertCircle, CheckCircle2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { z } from 'zod';

interface OrderEntryPanelProps {
  symbol?: string;
  selectedOption?: {
    strike: number;
    type: 'call' | 'put';
    last: number;
    bid: number;
    ask: number;
    delta: number;
  } | null;
  calculatedSize?: number;
  loading?: boolean;
}

type OrderType = 'market' | 'limit';
type TimeInForce = 'day' | 'gtc' | 'ioc' | 'fok';
type OrderAction = 'buy' | 'sell';

const orderSchema = z.object({
  quantity: z.number().positive({ message: "Quantity must be positive" }).int({ message: "Must be whole number" }),
  limitPrice: z.number().positive({ message: "Price must be positive" }).optional(),
});

export function OrderEntryPanel({
  symbol = 'SPY',
  selectedOption = null,
  calculatedSize = 0,
  loading = false,
}: OrderEntryPanelProps) {
  const [orderType, setOrderType] = useState<OrderType>('limit');
  const [timeInForce, setTimeInForce] = useState<TimeInForce>('day');
  const [quantity, setQuantity] = useState<string>('');
  const [limitPrice, setLimitPrice] = useState<string>('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Auto-fill quantity when calculated size changes
  useEffect(() => {
    if (calculatedSize > 0) {
      setQuantity(calculatedSize.toString());
    }
  }, [calculatedSize]);

  // Auto-fill limit price with mid-price when option changes
  useEffect(() => {
    if (selectedOption && orderType === 'limit') {
      const midPrice = (selectedOption.bid + selectedOption.ask) / 2;
      setLimitPrice(midPrice.toFixed(2));
    }
  }, [selectedOption, orderType]);

  const validateOrder = () => {
    try {
      const parsed = orderSchema.parse({
        quantity: parseInt(quantity) || 0,
        limitPrice: orderType === 'limit' ? parseFloat(limitPrice) : undefined,
      });

      if (orderType === 'limit' && !parsed.limitPrice) {
        setErrors({ limitPrice: 'Limit price required for limit orders' });
        return null;
      }

      setErrors({});
      return parsed;
    } catch (error) {
      if (error instanceof z.ZodError) {
        const newErrors: Record<string, string> = {};
        error.errors.forEach((err) => {
          if (err.path[0]) {
            newErrors[err.path[0].toString()] = err.message;
          }
        });
        setErrors(newErrors);
      }
      return null;
    }
  };

  const handleSubmitOrder = async (action: OrderAction) => {
    if (!selectedOption) {
      toast.error('No Contract Selected', {
        description: 'Please select an option contract first',
      });
      return;
    }

    const validated = validateOrder();
    if (!validated) {
      toast.error('Invalid Order', {
        description: 'Please check your order parameters',
      });
      return;
    }

    setIsSubmitting(true);

    // Simulate order submission
    try {
      await new Promise(resolve => setTimeout(resolve, 1000));

      const orderDetails = {
        symbol,
        action: action.toUpperCase(),
        contract: `${symbol} ${selectedOption.strike} ${selectedOption.type.toUpperCase()}`,
        quantity: validated.quantity,
        orderType: orderType.toUpperCase(),
        price: orderType === 'limit' ? `$${validated.limitPrice}` : 'MARKET',
        timeInForce: timeInForce.toUpperCase(),
        estimatedValue: validated.quantity * (orderType === 'limit' ? validated.limitPrice! : selectedOption.last) * 100,
      };

      toast.success('Order Submitted', {
        description: (
          <div className="space-y-1 text-xs">
            <div className="font-semibold">
              {orderDetails.action} {orderDetails.quantity} {orderDetails.contract}
            </div>
            <div className="text-muted-foreground">
              {orderDetails.orderType} @ {orderDetails.price} | {orderDetails.timeInForce}
            </div>
            <div className="text-muted-foreground">
              Est. Value: ${orderDetails.estimatedValue.toFixed(2)}
            </div>
          </div>
        ),
        duration: 5000,
      });

      // Log to console for debugging
      console.log('Order submitted:', orderDetails);
    } catch (error) {
      toast.error('Order Failed', {
        description: error instanceof Error ? error.message : 'Unknown error occurred',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Order Entry</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="h-10 bg-muted/50 rounded animate-pulse" />
            <div className="h-10 bg-muted/50 rounded animate-pulse" />
            <div className="h-10 bg-muted/50 rounded animate-pulse" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!selectedOption) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Send className="h-4 w-4" />
            Order Entry
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <AlertCircle className="h-8 w-8 text-muted-foreground mb-2" />
            <p className="text-sm text-muted-foreground">
              Select a contract from the options chain to begin
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const estimatedCost = orderType === 'limit' 
    ? (parseFloat(limitPrice) || 0) * (parseInt(quantity) || 0) * 100
    : selectedOption.last * (parseInt(quantity) || 0) * 100;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <Send className="h-4 w-4" />
            Order Entry
          </CardTitle>
          <Badge variant="outline">{symbol}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Selected Contract Summary */}
        <div className="p-3 bg-muted/30 border border-border rounded-lg">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-muted-foreground">Selected Contract</span>
            <Badge 
              variant="outline" 
              className={selectedOption.type === 'call' ? 'bg-green-500/10 text-green-400 border-green-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'}
            >
              {selectedOption.type.toUpperCase()}
            </Badge>
          </div>
          <div className="text-sm font-mono font-bold">
            ${selectedOption.strike} {selectedOption.type.toUpperCase()}
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground mt-1">
            <span>Bid: ${selectedOption.bid.toFixed(2)}</span>
            <span>Ask: ${selectedOption.ask.toFixed(2)}</span>
            <span>Last: ${selectedOption.last.toFixed(2)}</span>
          </div>
        </div>

        {/* Order Type */}
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">Order Type</Label>
          <Select value={orderType} onValueChange={(v) => setOrderType(v as OrderType)}>
            <SelectTrigger className="bg-background">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-popover border-border z-50">
              <SelectItem value="market" className="hover:bg-muted">Market</SelectItem>
              <SelectItem value="limit" className="hover:bg-muted">Limit</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Quantity */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="quantity" className="text-xs text-muted-foreground">
              Quantity (Contracts)
            </Label>
            {calculatedSize > 0 && (
              <Badge variant="secondary" className="text-xs">
                Suggested: {calculatedSize}
              </Badge>
            )}
          </div>
          <Input
            id="quantity"
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            placeholder="0"
            min="1"
            step="1"
          />
          {errors.quantity && (
            <p className="text-xs text-destructive flex items-center gap-1">
              <AlertCircle className="h-3 w-3" />
              {errors.quantity}
            </p>
          )}
          {quantity && (
            <p className="text-xs text-muted-foreground">
              Controls {(parseInt(quantity) * 100).toLocaleString()} shares (Delta-adjusted: {Math.abs(parseInt(quantity) * 100 * selectedOption.delta).toFixed(0)})
            </p>
          )}
        </div>

        {/* Limit Price (only for limit orders) */}
        {orderType === 'limit' && (
          <div className="space-y-2">
            <Label htmlFor="limitPrice" className="text-xs text-muted-foreground">
              Limit Price ($)
            </Label>
            <Input
              id="limitPrice"
              type="number"
              value={limitPrice}
              onChange={(e) => setLimitPrice(e.target.value)}
              placeholder="0.00"
              step="0.01"
              min="0.01"
            />
            {errors.limitPrice && (
              <p className="text-xs text-destructive flex items-center gap-1">
                <AlertCircle className="h-3 w-3" />
                {errors.limitPrice}
              </p>
            )}
          </div>
        )}

        {/* Time in Force */}
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">Time in Force</Label>
          <Select value={timeInForce} onValueChange={(v) => setTimeInForce(v as TimeInForce)}>
            <SelectTrigger className="bg-background">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-popover border-border z-50">
              <SelectItem value="day" className="hover:bg-muted">Day</SelectItem>
              <SelectItem value="gtc" className="hover:bg-muted">GTC (Good Till Cancelled)</SelectItem>
              <SelectItem value="ioc" className="hover:bg-muted">IOC (Immediate or Cancel)</SelectItem>
              <SelectItem value="fok" className="hover:bg-muted">FOK (Fill or Kill)</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Order Summary */}
        {quantity && (
          <div className="p-3 bg-primary/5 border border-primary/20 rounded-lg space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Estimated Cost:</span>
              <span className="font-mono font-semibold text-foreground">
                ${estimatedCost.toFixed(2)}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Per Contract:</span>
              <span className="font-mono text-foreground">
                ${(estimatedCost / (parseInt(quantity) || 1)).toFixed(2)}
              </span>
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="grid grid-cols-2 gap-2">
          <Button
            onClick={() => handleSubmitOrder('buy')}
            disabled={isSubmitting || !quantity}
            className="bg-green-600 hover:bg-green-700 text-white"
          >
            {isSubmitting ? (
              'Processing...'
            ) : (
              <>
                <TrendingUp className="h-4 w-4 mr-2" />
                Buy to Open
              </>
            )}
          </Button>
          <Button
            onClick={() => handleSubmitOrder('sell')}
            disabled={isSubmitting || !quantity}
            variant="destructive"
          >
            {isSubmitting ? (
              'Processing...'
            ) : (
              <>
                <TrendingDown className="h-4 w-4 mr-2" />
                Sell to Open
              </>
            )}
          </Button>
        </div>

        {/* Disclaimer */}
        <div className="flex items-start gap-2 p-2 bg-muted/30 rounded text-xs text-muted-foreground">
          <AlertCircle className="h-3 w-3 mt-0.5 flex-shrink-0" />
          <p>
            This is a demo order system. No actual trades will be executed.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
