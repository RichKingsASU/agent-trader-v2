import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Power, ShoppingCart, TrendingDown } from "lucide-react";
import { useState } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface BotControls {
  bot_enabled: boolean;
  buying_enabled: boolean;
  selling_enabled: boolean;
}

interface ChartHUDProps {
  controls: BotControls;
  onControlChange: (controls: BotControls) => void;
  onPanic: () => void;
  botStatus: "in_trade" | "flat";
}

export function ChartHUD({ controls, onControlChange, onPanic, botStatus }: ChartHUDProps) {
  const [showPanicDialog, setShowPanicDialog] = useState(false);

  const handleToggle = (key: keyof BotControls) => {
    onControlChange({
      ...controls,
      [key]: !controls[key],
    });
  };

  const handlePanicConfirm = () => {
    onPanic();
    setShowPanicDialog(false);
  };

  const isSystemReady = controls.bot_enabled && controls.buying_enabled && controls.selling_enabled;
  const statusColor = isSystemReady ? "bg-bull" : "bg-bear";
  const statusText = isSystemReady ? "SYSTEM READY" : "SYSTEM HALTED";

  return (
    <>
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10">
        {/* Status Pill - Glass Effect */}
        <div className="backdrop-blur-md bg-card/80 border border-white/20 rounded-full px-6 py-3 shadow-2xl">
          <div className="flex items-center gap-4">
            {/* Status Indicator */}
            <div className="flex items-center gap-2">
              <div className={`h-3 w-3 rounded-full ${statusColor} animate-pulse shadow-lg`}></div>
              <span className="text-sm font-bold ui-label tracking-wide">{statusText}</span>
            </div>

            <div className="h-6 w-px bg-white/20"></div>

            {/* Bot Controls - Compact */}
            <div className="flex items-center gap-3">
              {/* Bot Power */}
              <div className="flex items-center gap-1.5">
                <Power className={`h-3.5 w-3.5 ${controls.bot_enabled ? "text-bull" : "text-muted-foreground"}`} />
                <Switch
                  checked={controls.bot_enabled}
                  onCheckedChange={() => handleToggle("bot_enabled")}
                  className="data-[state=checked]:bg-bull scale-75"
                />
              </div>

              {/* Buy Toggle */}
              <div className="flex items-center gap-1.5">
                <ShoppingCart className={`h-3.5 w-3.5 ${controls.buying_enabled ? "text-bull" : "text-muted-foreground"}`} />
                <Switch
                  checked={controls.buying_enabled}
                  onCheckedChange={() => handleToggle("buying_enabled")}
                  className="data-[state=checked]:bg-bull scale-75"
                />
              </div>

              {/* Sell Toggle */}
              <div className="flex items-center gap-1.5">
                <TrendingDown className={`h-3.5 w-3.5 ${controls.selling_enabled ? "text-bear" : "text-muted-foreground"}`} />
                <Switch
                  checked={controls.selling_enabled}
                  onCheckedChange={() => handleToggle("selling_enabled")}
                  className="data-[state=checked]:bg-bear scale-75"
                />
              </div>
            </div>

            <div className="h-6 w-px bg-white/20"></div>

            {/* Panic Button */}
            <Button
              variant="destructive"
              size="sm"
              className="h-7 px-3 text-xs font-bold shadow-lg"
              onClick={() => setShowPanicDialog(true)}
            >
              <AlertTriangle className="mr-1 h-3 w-3" />
              PANIC
            </Button>
          </div>
        </div>
      </div>

      {/* Panic Confirmation Dialog */}
      <AlertDialog open={showPanicDialog} onOpenChange={setShowPanicDialog}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2 text-destructive text-xl">
              <AlertTriangle className="h-6 w-6" />
              Confirm Panic Action
            </AlertDialogTitle>
            <AlertDialogDescription className="text-base pt-2">
              <p className="mb-3 font-semibold">This will immediately:</p>
              <ul className="list-disc list-inside space-y-2 text-sm">
                <li>Liquidate all open positions at market price</li>
                <li>Cancel all pending orders</li>
                <li>Disable bot trading (all toggles off)</li>
              </ul>
              <p className="mt-4 font-semibold text-destructive">
                This action cannot be undone. Are you absolutely sure?
              </p>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handlePanicConfirm}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Yes, Execute PANIC
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
