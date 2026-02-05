import { useEffect, useState } from "react";
import { doc, onSnapshot, updateDoc } from "firebase/firestore";
import { db } from "@/firebase";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, Shield } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

/**
 * ShadowToggle Component
 * 
 * High-visibility toggle for Shadow Mode that controls whether trades
 * are simulated (shadow mode) or executed live with the broker.
 * 
 * Shadow Mode ON (default): All trades are simulated, no broker contact
 * Shadow Mode OFF: Trades are submitted to the broker (Alpaca)
 * 
 * Fail-safe: Defaults to shadow mode = TRUE on any errors.
 */
export const ShadowToggle = () => {
  const [isShadowMode, setIsShadowMode] = useState<boolean>(true); // Fail-safe default
  const [loading, setLoading] = useState<boolean>(true);
  const { toast } = useToast();

  useEffect(() => {
    // Subscribe to systemStatus/config document
    const configRef = doc(db!, "systemStatus", "config");

    const unsubscribe = onSnapshot(
      configRef,
      (snapshot) => {
        if (snapshot.exists()) {
          const data = snapshot.data();
          // Fail-safe: default to true if field is missing
          const shadowMode = data.is_shadow_mode ?? true;
          setIsShadowMode(shadowMode);
        } else {
          // Document doesn't exist, default to shadow mode
          console.warn("systemStatus/config not found, defaulting to shadow mode");
          setIsShadowMode(true);
        }
        setLoading(false);
      },
      (error) => {
        console.error("Error subscribing to shadow mode config:", error);
        // Fail-safe: on error, default to shadow mode
        setIsShadowMode(true);
        setLoading(false);
        toast({
          title: "Configuration Error",
          description: "Could not load shadow mode status. Defaulting to SHADOW MODE for safety.",
          variant: "destructive",
        });
      }
    );

    return () => unsubscribe();
  }, [toast]);

  const handleToggle = async (checked: boolean) => {
    try {
      const configRef = doc(db!, "systemStatus", "config");
      await updateDoc(configRef, {
        is_shadow_mode: checked,
        updated_at: new Date(),
      });

      toast({
        title: checked ? "Shadow Mode Enabled" : "⚠️ Shadow Mode Disabled",
        description: checked
          ? "All trades will be simulated. No broker contact."
          : "⚠️ Trades will be submitted to the broker. Use with caution.",
        variant: checked ? "default" : "destructive",
      });
    } catch (error) {
      console.error("Error updating shadow mode:", error);
      toast({
        title: "Update Failed",
        description: "Could not update shadow mode. Please try again.",
        variant: "destructive",
      });
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-border bg-card/50">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-muted border-t-primary" />
        <span className="text-sm text-muted-foreground">Loading...</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 px-4 py-2 rounded-lg border-2 border-border bg-card/80 shadow-sm hover:shadow-md transition-all">
      {/* Icon & Label */}
      <div className="flex items-center gap-2">
        {isShadowMode ? (
          <Shield className="h-5 w-5 text-amber-500" />
        ) : (
          <AlertTriangle className="h-5 w-5 text-red-500" />
        )}
        <span className="text-sm font-semibold text-foreground">Shadow Mode</span>
      </div>

      {/* Switch */}
      <Switch
        checked={isShadowMode}
        onCheckedChange={handleToggle}
        className={
          isShadowMode
            ? "data-[state=checked]:bg-amber-500"
            : "data-[state=unchecked]:bg-red-500/20"
        }
      />

      {/* Status Badge */}
      <Badge
        className={
          isShadowMode
            ? "bg-amber-500/20 text-amber-600 border border-amber-500/30 font-semibold"
            : "bg-red-500/20 text-red-600 border border-red-500/30 font-semibold animate-pulse"
        }
      >
        {isShadowMode ? "SIMULATED" : "⚠️ LIVE"}
      </Badge>
    </div>
  );
};
