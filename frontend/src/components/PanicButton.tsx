import { useState } from "react";
import { httpsCallable } from "firebase/functions";
import { functions } from "@/firebase";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { AlertTriangle, Loader2 } from "lucide-react";

interface EmergencyLiquidateResponse {
  success: boolean;
  message: string;
  positions_closed: number;
  orders_canceled: number;
}

export function PanicButton({
  variant = "full",
  className,
}: {
  variant?: "full" | "compact";
  className?: string;
}) {
  const [isExecuting, setIsExecuting] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const { toast } = useToast();

  const handleEmergencyLiquidate = async () => {
    setIsExecuting(true);

    try {
      if (!functions) {
        throw new Error("Emergency liquidation is not available (Firebase Functions not configured).");
      }
      // Call the Firebase Cloud Function
      const emergencyLiquidate = httpsCallable<void, EmergencyLiquidateResponse>(
        functions,
        "emergency_liquidate"
      );

      const result = await emergencyLiquidate();
      const data = result.data;

      if (data.success) {
        toast({
          title: "🚨 Emergency Liquidation Successful",
          description: `Closed ${data.positions_closed} positions and canceled ${data.orders_canceled} orders. Trading is now halted.`,
          variant: "default",
        });
      } else {
        throw new Error(data.message || "Unknown error occurred");
      }

      // Close the dialog
      setIsOpen(false);
    } catch (error) {
      console.error("Emergency liquidation failed:", error);
      
      toast({
        title: "❌ Emergency Liquidation Failed",
        description: error instanceof Error ? error.message : "An unknown error occurred. Check console for details.",
        variant: "destructive",
      });
    } finally {
      setIsExecuting(false);
    }
  };

  return (
    <AlertDialog open={isOpen} onOpenChange={setIsOpen}>
      <AlertDialogTrigger asChild>
        <Button
          variant="destructive"
          size={variant === "compact" ? "sm" : "lg"}
          className={[
            "bg-red-600 hover:bg-red-700 text-white font-bold shadow-lg border-2 border-red-800",
            variant === "compact" ? "animate-none" : "animate-pulse",
            className ?? "",
          ].join(" ")}
        >
          <AlertTriangle className={variant === "compact" ? "mr-2 h-4 w-4" : "mr-2 h-5 w-5"} />
          {variant === "compact" ? "PANIC" : "🚨 NUCLEAR PANIC"}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent className="border-red-500 border-2">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-red-600 text-2xl flex items-center gap-2">
            <AlertTriangle className="h-6 w-6" />
            Emergency Liquidation Confirmation
          </AlertDialogTitle>
          <AlertDialogDescription className="text-base space-y-3">
            <p className="font-semibold text-foreground">
              ⚠️ WARNING: This action is irreversible and will:
            </p>
            <ul className="list-disc list-inside space-y-1 text-left">
              <li>Immediately close ALL open positions</li>
              <li>Cancel ALL pending orders</li>
              <li>Lock the trading gate (trading_enabled = false)</li>
              <li>Set system status to EMERGENCY_HALT</li>
            </ul>
            <p className="font-semibold text-red-600 mt-4">
              Are you absolutely sure you want to proceed?
            </p>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isExecuting}>
            Cancel - Keep Trading
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              e.preventDefault();
              handleEmergencyLiquidate();
            }}
            disabled={isExecuting}
            className="bg-red-600 hover:bg-red-700 text-white"
          >
            {isExecuting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Executing...
              </>
            ) : (
              <>
                <AlertTriangle className="mr-2 h-4 w-4" />
                YES - LIQUIDATE NOW
              </>
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
