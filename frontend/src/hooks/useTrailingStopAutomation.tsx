import { useEffect, useState, useRef } from 'react';
import { toast } from 'sonner';
import {
  StopLossConfig,
  PositionInfo,
  calculateStopLevel,
  shouldUpdateTrailingStop,
  calculateStopDistance,
} from '@/utils/stopCalculations';

interface TrailingStopAutomationProps {
  position: PositionInfo;
  config: StopLossConfig;
  enabled: boolean;
  atrValue?: number;
}

interface TrailingStopState {
  currentStopLevel: number;
  highestPrice: number;
  lowestPrice: number;
  lastAdjustmentPrice: number;
}

/**
 * Hook to automate trailing stop adjustments based on real-time price movements
 */
export function useTrailingStopAutomation({
  position,
  config,
  enabled,
  atrValue = 2.5,
}: TrailingStopAutomationProps) {
  const [stopState, setStopState] = useState<TrailingStopState>({
    currentStopLevel: position.entryPrice,
    highestPrice: position.highestPrice || position.entryPrice,
    lowestPrice: position.lowestPrice || position.entryPrice,
    lastAdjustmentPrice: position.entryPrice,
  });

  const prevStopLevel = useRef<number>(stopState.currentStopLevel);

  useEffect(() => {
    if (!enabled || config.type !== 'trailing') {
      return;
    }

    const currentPrice = position.currentPrice;

    // Update highest/lowest prices
    let newHighest = stopState.highestPrice;
    let newLowest = stopState.lowestPrice;
    let shouldUpdate = false;

    if (position.side === 'long') {
      if (currentPrice > stopState.highestPrice) {
        newHighest = currentPrice;
        shouldUpdate = true;
      }
    } else {
      if (currentPrice < stopState.lowestPrice) {
        newLowest = currentPrice;
        shouldUpdate = true;
      }
    }

    if (shouldUpdate) {
      // Check if price has moved enough to warrant trailing stop adjustment
      const updatedPosition: PositionInfo = {
        ...position,
        highestPrice: newHighest,
        lowestPrice: newLowest,
      };

      const minThreshold = atrValue * 0.5; // Minimum 0.5 ATR move before adjusting
      const shouldAdjust = shouldUpdateTrailingStop(updatedPosition, minThreshold);

      if (shouldAdjust) {
        const newStopLevel = calculateStopLevel(updatedPosition, config);
        const distance = calculateStopDistance(currentPrice, newStopLevel, atrValue);

        setStopState({
          currentStopLevel: newStopLevel,
          highestPrice: newHighest,
          lowestPrice: newLowest,
          lastAdjustmentPrice: currentPrice,
        });

        // Send toast notification if stop level actually changed
        if (Math.abs(newStopLevel - prevStopLevel.current) > 0.01) {
          prevStopLevel.current = newStopLevel;

          toast.success('Trailing Stop Adjusted', {
            description: `New stop level: $${newStopLevel.toFixed(2)} (${distance.percent.toFixed(2)}% / ${distance.atr?.toFixed(2)} ATR from current price)`,
            duration: 4000,
          });
        }
      }
    }
  }, [position, config, enabled, atrValue, stopState]);

  // Initialize stop level on mount or config change
  useEffect(() => {
    if (enabled) {
      const initialStopLevel = calculateStopLevel(
        {
          ...position,
          highestPrice: stopState.highestPrice,
          lowestPrice: stopState.lowestPrice,
        },
        config
      );
      
      setStopState(prev => ({
        ...prev,
        currentStopLevel: initialStopLevel,
      }));
      
      prevStopLevel.current = initialStopLevel;
    }
  }, [config.type, config.fixedPrice, config.trailingDistance, config.trailingUnit, enabled]);

  return {
    currentStopLevel: stopState.currentStopLevel,
    highestPrice: stopState.highestPrice,
    lowestPrice: stopState.lowestPrice,
    distance: calculateStopDistance(
      position.currentPrice,
      stopState.currentStopLevel,
      atrValue
    ),
  };
}
