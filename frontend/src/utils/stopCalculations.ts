/**
 * Utility functions for stop-loss and trailing stop calculations
 */

export interface StopLossConfig {
  type: 'fixed' | 'trailing';
  fixedPrice?: number;
  trailingDistance?: number;
  trailingUnit: 'percent' | 'atr';
  atrValue?: number;
}

export interface PositionInfo {
  side: 'long' | 'short';
  entryPrice: number;
  currentPrice: number;
  highestPrice?: number; // For long positions
  lowestPrice?: number;  // For short positions
}

/**
 * Calculate the active stop level based on configuration and position
 */
export function calculateStopLevel(
  position: PositionInfo,
  config: StopLossConfig
): number {
  if (config.type === 'fixed' && config.fixedPrice) {
    return config.fixedPrice;
  }

  if (config.type === 'trailing' && config.trailingDistance) {
    const distance = calculateTrailingDistance(config);
    
    if (position.side === 'long') {
      // For long: stop below the highest price reached
      const referencePrice = position.highestPrice || position.entryPrice;
      return referencePrice - distance;
    } else {
      // For short: stop above the lowest price reached
      const referencePrice = position.lowestPrice || position.entryPrice;
      return referencePrice + distance;
    }
  }

  // Default: stop at entry (break-even)
  return position.entryPrice;
}

/**
 * Calculate trailing distance in dollar terms
 */
function calculateTrailingDistance(config: StopLossConfig): number {
  if (!config.trailingDistance) return 0;

  if (config.trailingUnit === 'atr' && config.atrValue) {
    return config.trailingDistance * config.atrValue;
  }

  // Percent-based (will need to be multiplied by price later)
  return config.trailingDistance;
}

/**
 * Check if trailing stop should be updated
 * Returns new reference price if stop should move, otherwise null
 */
export function shouldUpdateTrailingStop(
  position: PositionInfo,
  minThreshold: number // e.g., 0.5 ATR
): boolean {
  if (position.side === 'long') {
    const moveFromEntry = position.currentPrice - position.entryPrice;
    return moveFromEntry >= minThreshold;
  } else {
    const moveFromEntry = position.entryPrice - position.currentPrice;
    return moveFromEntry >= minThreshold;
  }
}

/**
 * Calculate distance from current price to stop level
 */
export function calculateStopDistance(
  currentPrice: number,
  stopLevel: number,
  atrValue?: number
): { percent: number; atr?: number; dollars: number } {
  const dollars = Math.abs(currentPrice - stopLevel);
  const percent = (dollars / currentPrice) * 100;
  const atr = atrValue ? dollars / atrValue : undefined;

  return { percent, atr, dollars };
}

/**
 * Calculate Risk:Reward ratio given entry, stop, and target
 */
export function calculateRiskReward(
  entryPrice: number,
  stopPrice: number,
  targetPrice: number
): number {
  const risk = Math.abs(entryPrice - stopPrice);
  const reward = Math.abs(targetPrice - entryPrice);
  
  if (risk === 0) return 0;
  return reward / risk;
}

/**
 * Calculate win rate from trade history
 */
export function calculateWinRate(trades: Array<{ pnl: number }>): number {
  if (trades.length === 0) return 0;
  const wins = trades.filter(t => t.pnl > 0).length;
  return (wins / trades.length) * 100;
}

/**
 * Calculate average R:R from trade history
 */
export function calculateAverageRR(
  trades: Array<{ entry: number; exit: number; stop: number; side: 'long' | 'short' }>
): number {
  if (trades.length === 0) return 0;

  const rrValues = trades.map(trade => {
    const risk = Math.abs(trade.entry - trade.stop);
    const reward = Math.abs(trade.exit - trade.entry);
    return risk > 0 ? reward / risk : 0;
  });

  return rrValues.reduce((sum, rr) => sum + rr, 0) / rrValues.length;
}

/**
 * Calculate trading edge
 */
export function calculateEdge(
  winRate: number,
  avgWin: number,
  avgLoss: number
): number {
  const lossRate = 1 - winRate / 100;
  return (avgWin * winRate / 100) - (avgLoss * lossRate);
}
