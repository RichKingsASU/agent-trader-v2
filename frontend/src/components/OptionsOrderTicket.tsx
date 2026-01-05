import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Plus, Trash2, FileText, Lock, Unlock } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";

type Strategy = "single" | "vertical" | "iron_condor" | "strangle" | "straddle" | "custom";
type LegSide = "buy_to_open" | "sell_to_open" | "buy_to_close" | "sell_to_close";
type OptionType = "call" | "put";

interface Leg {
  id: string;
  side: LegSide;
  quantity: number;
  expiry: string;
  strike: number;
  type: OptionType;
}

interface OptionsOrderTicketProps {
  defaultSymbol: string;
}

export function OptionsOrderTicket({ defaultSymbol }: OptionsOrderTicketProps) {
  const [strategy, setStrategy] = useState<Strategy>("single");
  const [legs, setLegs] = useState<Leg[]>([
    {
      id: "1",
      side: "buy_to_open",
      quantity: 1,
      expiry: "2024-12-20",
      strike: 430,
      type: "call",
    },
  ]);
  const [orderType, setOrderType] = useState<"limit" | "market">("limit");
  const [price, setPrice] = useState("2.50");
  const [timeInForce, setTimeInForce] = useState<"day" | "gtc">("day");
  const [showReviewDialog, setShowReviewDialog] = useState(false);
  const [isLocked, setIsLocked] = useState(true);

  const strategyTemplates: Record<Strategy, number> = {
    single: 1,
    vertical: 2,
    iron_condor: 4,
    strangle: 2,
    straddle: 2,
    custom: 1,
  };

  const handleStrategyChange = (newStrategy: Strategy) => {
    setStrategy(newStrategy);
    const numLegs = strategyTemplates[newStrategy];
    
    // Reset legs based on strategy
    const newLegs: Leg[] = Array.from({ length: numLegs }, (_, i) => ({
      id: String(i + 1),
      side: i === 0 ? "buy_to_open" : "sell_to_open",
      quantity: 1,
      expiry: "2024-12-20",
      strike: 430 + i * 5,
      type: "call",
    }));
    
    setLegs(newLegs);
  };

  const addLeg = () => {
    const newLeg: Leg = {
      id: String(Date.now()),
      side: "buy_to_open",
      quantity: 1,
      expiry: "2024-12-20",
      strike: 430,
      type: "call",
    };
    setLegs([...legs, newLeg]);
  };

  const removeLeg = (id: string) => {
    if (legs.length > 1) {
      setLegs(legs.filter(leg => leg.id !== id));
    }
  };

  const updateLeg = (id: string, field: keyof Leg, value: any) => {
    setLegs(legs.map(leg => leg.id === id ? { ...leg, [field]: value } : leg));
  };

  const handleReview = () => {
    setShowReviewDialog(true);
  };

  const handleSubmit = () => {
    toast.success("Order submitted successfully");
    setShowReviewDialog(false);
    // TODO: POST to /api/orders/options_complex
  };

  const getLegDescription = (leg: Leg) => {
    const side = leg.side === "buy_to_open" ? "+" : "-";
    return `${side}${leg.quantity} ${leg.expiry.slice(5)} ${leg.strike}${leg.type.charAt(0).toUpperCase()}`;
  };

  return (
    <Card className="p-5 transition-opacity duration-200 hover:opacity-100 focus-within:opacity-100 opacity-75">
      <div className="space-y-5">
        {/* Header */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold ui-label">Options Order Ticket</h3>
            <div className="flex items-center gap-2">
              <Button
                variant={isLocked ? "outline" : "default"}
                size="sm"
                onClick={() => setIsLocked(!isLocked)}
                className="h-7 px-2"
              >
                {isLocked ? (
                  <>
                    <Lock className="h-3 w-3 mr-1" />
                    <span className="text-xs">Locked</span>
                  </>
                ) : (
                  <>
                    <Unlock className="h-3 w-3 mr-1" />
                    <span className="text-xs">Unlocked</span>
                  </>
                )}
              </Button>
              <Badge variant="outline" className="text-xs font-semibold">
                {defaultSymbol}
              </Badge>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            {isLocked ? "Click 'Unlock' to adjust values" : "Build and submit options orders"}
          </p>
        </div>

        <Separator />

        {/* Strategy Selector */}
        <div className="space-y-2">
          <Label className="text-xs font-semibold uppercase tracking-wide ui-label">Strategy</Label>
          <Select value={strategy} onValueChange={(v) => handleStrategyChange(v as Strategy)} disabled={isLocked}>
            <SelectTrigger className="bg-background">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-popover border-border z-[100]">
              <SelectItem value="single">Single Leg</SelectItem>
              <SelectItem value="vertical">Vertical Spread</SelectItem>
              <SelectItem value="iron_condor">Iron Condor</SelectItem>
              <SelectItem value="strangle">Strangle</SelectItem>
              <SelectItem value="straddle">Straddle</SelectItem>
              <SelectItem value="custom">Custom</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Legs Builder */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <Label className="text-xs font-semibold uppercase tracking-wide ui-label">Legs</Label>
            {strategy === "custom" && (
              <Button size="sm" variant="outline" onClick={addLeg} className="h-7 text-xs" disabled={isLocked}>
                <Plus className="h-3 w-3 mr-1" />
                Add Leg
              </Button>
            )}
          </div>

          <div className="space-y-2">
            {legs.map((leg, index) => (
              <div key={leg.id} className="border border-border rounded-md p-3 bg-card">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-muted-foreground">Leg {index + 1}</span>
                  {strategy === "custom" && legs.length > 1 && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => removeLeg(leg.id)}
                      className="h-6 w-6 p-0 hover:bg-destructive/10 hover:text-destructive"
                      disabled={isLocked}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  )}
                </div>
                
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <Label className="text-[10px] text-muted-foreground uppercase ui-label">Side</Label>
                    <Select value={leg.side} onValueChange={(v) => updateLeg(leg.id, "side", v)} disabled={isLocked}>
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-popover z-[100]">
                        <SelectItem value="buy_to_open">Buy to Open</SelectItem>
                        <SelectItem value="sell_to_open">Sell to Open</SelectItem>
                        <SelectItem value="buy_to_close">Buy to Close</SelectItem>
                        <SelectItem value="sell_to_close">Sell to Close</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div>
                    <Label className="text-[10px] text-muted-foreground uppercase ui-label">Qty</Label>
                    <Input
                      type="number"
                      value={leg.quantity}
                      onChange={(e) => updateLeg(leg.id, "quantity", parseInt(e.target.value))}
                      className="h-8 text-xs"
                      min={1}
                      disabled={isLocked}
                    />
                  </div>

                  <div>
                    <Label className="text-[10px] text-muted-foreground uppercase ui-label">Strike</Label>
                    <Input
                      type="number"
                      value={leg.strike}
                      onChange={(e) => updateLeg(leg.id, "strike", parseFloat(e.target.value))}
                      className="h-8 text-xs"
                      step={1}
                      disabled={isLocked}
                    />
                  </div>

                  <div>
                    <Label className="text-[10px] text-muted-foreground uppercase ui-label">Type</Label>
                    <Select value={leg.type} onValueChange={(v) => updateLeg(leg.id, "type", v)} disabled={isLocked}>
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-popover z-[100]">
                        <SelectItem value="call">Call</SelectItem>
                        <SelectItem value="put">Put</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <Separator />

        {/* Order Details */}
        <div className="space-y-3">
          <Label className="text-xs font-semibold uppercase tracking-wide ui-label">Order Details</Label>
          
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[10px] text-muted-foreground uppercase ui-label">Order Type</Label>
              <Select value={orderType} onValueChange={(v: any) => setOrderType(v)} disabled={isLocked}>
                <SelectTrigger className="h-9 text-xs bg-background">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-popover z-[100]">
                  <SelectItem value="limit">Limit</SelectItem>
                  <SelectItem value="market">Market</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-[10px] text-muted-foreground uppercase ui-label">
                {orderType === "limit" ? "Net Debit/Credit" : "Market"}
              </Label>
              <Input
                type="text"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                className="h-9 text-xs"
                disabled={orderType === "market" || isLocked}
                placeholder="0.00"
              />
            </div>
          </div>

          <div>
            <Label className="text-[10px] text-muted-foreground uppercase ui-label">Time in Force</Label>
            <Select value={timeInForce} onValueChange={(v: any) => setTimeInForce(v)} disabled={isLocked}>
              <SelectTrigger className="h-9 text-xs bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-popover z-[100]">
                <SelectItem value="day">Day</SelectItem>
                <SelectItem value="gtc">GTC (Good Till Cancelled)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Summary */}
        <div className="bg-muted/50 rounded-md p-3 space-y-1">
          <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">Order Summary</div>
          <div className="text-xs space-y-0.5">
            {legs.map((leg, i) => (
              <div key={leg.id} className="flex items-center justify-between">
                <span className="font-mono text-foreground">{getLegDescription(leg)}</span>
              </div>
            ))}
          </div>
          <Separator className="my-2" />
          <div className="text-xs space-y-0.5">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Max Profit:</span>
              <span className="font-semibold">–</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Max Loss:</span>
              <span className="font-semibold">–</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">BP Impact:</span>
              <span className="font-semibold">–</span>
            </div>
          </div>
        </div>

        {/* Submit Button */}
        <Button onClick={handleReview} className="w-full" size="lg" disabled={isLocked}>
          <FileText className="mr-2 h-4 w-4" />
          Review Order
        </Button>
      </div>

      {/* Review Dialog */}
      <Dialog open={showReviewDialog} onOpenChange={setShowReviewDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Review Options Order</DialogTitle>
            <DialogDescription>
              Please review your order details before submitting
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <Label className="text-xs text-muted-foreground">Underlying</Label>
              <div className="font-semibold">{defaultSymbol}</div>
            </div>

            <div>
              <Label className="text-xs text-muted-foreground">Strategy</Label>
              <div className="font-semibold capitalize">{strategy.replace("_", " ")}</div>
            </div>

            <div>
              <Label className="text-xs text-muted-foreground mb-2">Legs</Label>
              <div className="space-y-1">
                {legs.map((leg) => (
                  <div key={leg.id} className="text-sm font-mono bg-muted/50 px-3 py-2 rounded">
                    {getLegDescription(leg)}
                  </div>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label className="text-xs text-muted-foreground">Order Type</Label>
                <div className="font-semibold capitalize">{orderType}</div>
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">Time in Force</Label>
                <div className="font-semibold uppercase">{timeInForce}</div>
              </div>
            </div>

            {orderType === "limit" && (
              <div>
                <Label className="text-xs text-muted-foreground">Net Price</Label>
                <div className="font-semibold">${price}</div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowReviewDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleSubmit}>Submit Order</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
