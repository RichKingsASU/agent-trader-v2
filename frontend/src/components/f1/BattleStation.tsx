import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ArrowUpCircle, ArrowDownCircle, Target } from "lucide-react";
import { toast } from "sonner";

interface Level2Row {
  price: number;
  size: number;
  side: "bid" | "ask";
}

const mockLevel2Data: Level2Row[] = [
  { price: 432.25, size: 150, side: "ask" },
  { price: 432.20, size: 230, side: "ask" },
  { price: 432.18, size: 180, side: "ask" },
  { price: 432.15, size: 320, side: "ask" },
  { price: 432.12, size: 200, side: "bid" },
  { price: 432.10, size: 280, side: "bid" },
  { price: 432.08, size: 160, side: "bid" },
  { price: 432.05, size: 190, side: "bid" },
];

export const BattleStation = ({ symbol }: { symbol: string }) => {
  const [orderType, setOrderType] = useState<"market" | "limit">("limit");
  const [quantity, setQuantity] = useState("1");
  const [limitPrice, setLimitPrice] = useState("432.15");
  const [stopLoss, setStopLoss] = useState("430.00");

  const handleBuy = () => {
    toast.success(`BUY ${quantity} ${symbol} @ ${orderType === "market" ? "MARKET" : limitPrice}`, {
      description: `Stop Loss: $${stopLoss}`,
    });
  };

  const handleSell = () => {
    toast.error(`SELL ${quantity} ${symbol} @ ${orderType === "market" ? "MARKET" : limitPrice}`, {
      description: `Stop Loss: $${stopLoss}`,
    });
  };

  const maxBidSize = Math.max(...mockLevel2Data.filter(r => r.side === "bid").map(r => r.size));
  const maxAskSize = Math.max(...mockLevel2Data.filter(r => r.side === "ask").map(r => r.size));

  return (
    <Card className="h-full bg-card/30 backdrop-blur-sm border-white/10">
      <Tabs defaultValue="order" className="h-full">
        <TabsList className="w-full justify-start border-b border-white/10 rounded-none bg-transparent p-4">
          <TabsTrigger value="order" className="text-xs font-bold uppercase tracking-wider">
            Order Entry
          </TabsTrigger>
          <TabsTrigger value="level2" className="text-xs font-bold uppercase tracking-wider">
            Level 2
          </TabsTrigger>
        </TabsList>

        <TabsContent value="order" className="p-4 space-y-4 mt-0">
          <div className="grid grid-cols-2 gap-2">
            <Button
              variant={orderType === "market" ? "default" : "outline"}
              size="sm"
              onClick={() => setOrderType("market")}
              className="text-xs font-bold"
            >
              MARKET
            </Button>
            <Button
              variant={orderType === "limit" ? "default" : "outline"}
              size="sm"
              onClick={() => setOrderType("limit")}
              className="text-xs font-bold"
            >
              LIMIT
            </Button>
          </div>

          <div className="space-y-3">
            <div>
              <Label htmlFor="quantity" className="text-xs uppercase tracking-wide ui-label">
                Quantity
              </Label>
              <Input
                id="quantity"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                className="number-mono font-bold text-base bg-background/50 border-white/10"
              />
            </div>

            {orderType === "limit" && (
              <div>
                <Label htmlFor="limitPrice" className="text-xs uppercase tracking-wide ui-label">
                  Limit Price
                </Label>
                <Input
                  id="limitPrice"
                  value={limitPrice}
                  onChange={(e) => setLimitPrice(e.target.value)}
                  className="number-mono font-bold text-base bg-background/50 border-white/10"
                />
              </div>
            )}

            <div>
              <Label htmlFor="stopLoss" className="text-xs uppercase tracking-wide ui-label flex items-center gap-1">
                <Target className="h-3 w-3" />
                Stop Loss
              </Label>
              <Input
                id="stopLoss"
                value={stopLoss}
                onChange={(e) => setStopLoss(e.target.value)}
                className="number-mono font-bold text-base bg-background/50 border-white/10"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 pt-2">
            <Button
              size="lg"
              onClick={handleBuy}
              className="h-14 bg-bull hover:bg-bull/90 text-white font-bold text-base shadow-lg shadow-bull/20"
            >
              <ArrowUpCircle className="h-5 w-5 mr-2" />
              BUY
            </Button>
            <Button
              size="lg"
              onClick={handleSell}
              className="h-14 bg-bear hover:bg-bear/90 text-white font-bold text-base shadow-lg shadow-bear/20"
            >
              <ArrowDownCircle className="h-5 w-5 mr-2" />
              SELL
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="level2" className="mt-0 p-0">
          <ScrollArea className="h-[400px]">
            <div className="p-4 space-y-0.5">
              {mockLevel2Data.map((row, idx) => (
                <div
                  key={idx}
                  className={`relative flex items-center justify-between py-2 px-3 rounded ${
                    row.side === "ask" ? "bg-bear/5" : "bg-bull/5"
                  }`}
                >
                  {/* Background Bar */}
                  <div
                    className={`absolute inset-y-0 right-0 rounded ${
                      row.side === "ask" ? "bg-bear/10" : "bg-bull/10"
                    }`}
                    style={{
                      width: `${(row.size / (row.side === "ask" ? maxAskSize : maxBidSize)) * 100}%`,
                    }}
                  />
                  
                  <span className={`text-sm font-bold number-mono z-10 ${
                    row.side === "ask" ? "text-bear" : "text-bull"
                  }`}>
                    ${row.price.toFixed(2)}
                  </span>
                  <span className="text-sm font-medium number-mono z-10 opacity-70">
                    {row.size}
                  </span>
                </div>
              ))}
            </div>
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </Card>
  );
};
