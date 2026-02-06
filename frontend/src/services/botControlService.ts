/**
 * Bot Control Service
 *
 * Provides API integration for execution engine control commands.
 *
 * During Pre-Firebase Stabilization:
 * - Stubs are disabled by default (responses are logged only)
 * - Set VITE_ENABLE_BOT_CONTROL_API=true to enable production endpoints
 *
 * Post-launch:
 * - Implement with Cloud Functions or backend service
 */

export interface BotControls {
  bot_enabled: boolean;
  buying_enabled: boolean;
  selling_enabled: boolean;
}

const ENABLE_BOT_API = ((import.meta.env.VITE_ENABLE_BOT_CONTROL_API as string | undefined) ?? "false").trim().toLowerCase() === "true";

/**
 * Set bot control flags (enable/disable buying, selling, trading)
 */
export async function setBotControls(controls: BotControls): Promise<void> {
  if (!ENABLE_BOT_API) {
    console.info("[BOT_CONTROL_STUB] setBotControls:", controls);
    return;
  }

  try {
    const response = await fetch("/api/bot/set_controls", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(controls),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    console.info("[BOT_CONTROL] Controls set successfully");
  } catch (error) {
    console.error("[BOT_CONTROL_ERROR] Failed to set controls:", error);
    throw error;
  }
}

/**
 * Emergency stop: liquidate all positions and disable trading
 */
export async function panicStop(): Promise<void> {
  if (!ENABLE_BOT_API) {
    console.warn("[BOT_PANIC_STUB] Emergency stop triggered (not sent to backend)");
    return;
  }

  try {
    const response = await fetch("/api/bot/panic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    console.warn("[BOT_PANIC] Emergency stop executed");
  } catch (error) {
    console.error("[BOT_PANIC_ERROR] Failed to execute panic:", error);
    throw error;
  }
}
