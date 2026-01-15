import { useEffect, useState } from "react";
import { onSnapshot } from "firebase/firestore";
import { db } from "@/firebase";
import { Shield } from "lucide-react";
import { systemDoc } from "@/lib/tenancy/firestore";

/**
 * ShadowModeIndicator Component
 * 
 * Displays a prominent visual indicator when shadow mode is active.
 * Shows a subtle watermark overlay and a badge to remind users that
 * all trades are simulated.
 */
export const ShadowModeIndicator = () => {
  const [isShadowMode, setIsShadowMode] = useState<boolean>(true); // Fail-safe default
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    // Subscribe to systemStatus/config document
    const configRef = systemDoc(db, "config");
    
    const unsubscribe = onSnapshot(
      configRef,
      (snapshot) => {
        if (snapshot.exists()) {
          const data = snapshot.data();
          const shadowMode = data.is_shadow_mode ?? true;
          setIsShadowMode(shadowMode);
        } else {
          setIsShadowMode(true);
        }
        setLoading(false);
      },
      (error) => {
        console.error("Error subscribing to shadow mode indicator:", error);
        setIsShadowMode(true);
        setLoading(false);
      }
    );

    return () => unsubscribe();
  }, []);

  // Don't show indicator if loading or if shadow mode is off
  if (loading || !isShadowMode) {
    return null;
  }

  return (
    <>
      {/* Watermark Overlay */}
      <div className="fixed inset-0 pointer-events-none z-[9999] overflow-hidden">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 transform -rotate-45">
          <div className="text-[120px] font-black text-amber-500/5 whitespace-nowrap select-none">
            SIMULATED ENVIRONMENT
          </div>
        </div>
      </div>

      {/* Corner Badge */}
      <div className="fixed top-20 right-6 z-[9998] pointer-events-none">
        <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500/10 border-2 border-amber-500/30 backdrop-blur-sm shadow-lg">
          <Shield className="h-5 w-5 text-amber-600" />
          <div className="flex flex-col">
            <span className="text-xs font-bold text-amber-600 uppercase tracking-wide">
              Shadow Mode Active
            </span>
            <span className="text-[10px] text-amber-600/80">
              All trades are simulated
            </span>
          </div>
        </div>
      </div>
    </>
  );
};
