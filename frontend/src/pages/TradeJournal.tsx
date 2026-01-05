import { TradeJournal } from "@/components/JournalEntry";

/**
 * Trade Journal Page
 * 
 * Full-page view of the automated trading journal with AI-powered analysis.
 * Displays all journal entries with Quant Grades and actionable insights.
 * 
 * Features:
 * - Real-time updates via Firestore
 * - AI-powered trade analysis
 * - Quant Grade (A-F) visualization
 * - GEX regime context
 * - Actionable improvement suggestions
 */
export default function TradeJournalPage() {
  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <TradeJournal />
    </div>
  );
}
