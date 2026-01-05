import { useEffect, useRef, useState } from "react";
import { createChart, IChartApi, ISeriesApi, CandlestickData, Time, CandlestickSeries, LineSeries } from "lightweight-charts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface ExecutionChartProps {
  symbol: string;
  levelsData: any;
  currentPrice?: number;
  vwap?: number;
  atr?: number;
  loading: boolean;
}

export const ExecutionChart = ({ symbol, levelsData, currentPrice, vwap, atr, loading }: ExecutionChartProps) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const vwapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // Generate mock intraday 1m data
  const generateMockData = (): CandlestickData[] => {
    const data: CandlestickData[] = [];
    const now = new Date();
    const marketOpen = new Date(now);
    marketOpen.setHours(9, 30, 0, 0);

    const basePrice = currentPrice || 432;
    const points = 60; // 1 hour of 1-minute data

    for (let i = 0; i < points; i++) {
      const timestamp = new Date(marketOpen.getTime() + i * 60000);
      const variation = (Math.random() - 0.5) * 0.5;
      const open = basePrice + variation;
      const close = open + (Math.random() - 0.5) * 0.3;
      const high = Math.max(open, close) + Math.random() * 0.2;
      const low = Math.min(open, close) - Math.random() * 0.2;

      data.push({
        time: Math.floor(timestamp.getTime() / 1000) as Time,
        open,
        high,
        low,
        close,
      });
    }

    return data;
  };

  useEffect(() => {
    if (!chartContainerRef.current || loading) return;

    // Initialize chart with light theme
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 400,
      layout: {
        background: { color: "hsl(0, 0%, 100%)" },
        textColor: "hsl(222, 16%, 18%)",
      },
      grid: {
        vertLines: { color: "hsl(214, 15%, 91%)" },
        horzLines: { color: "hsl(214, 15%, 91%)" },
      },
      rightPriceScale: {
        borderColor: "hsl(214, 15%, 91%)",
      },
      timeScale: {
        borderColor: "hsl(214, 15%, 91%)",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    chartRef.current = chart;

    // Add candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "hsl(142, 76%, 36%)",
      downColor: "hsl(0, 72%, 51%)",
      borderUpColor: "hsl(142, 76%, 36%)",
      borderDownColor: "hsl(0, 72%, 51%)",
      wickUpColor: "hsl(142, 76%, 36%)",
      wickDownColor: "hsl(0, 72%, 51%)",
    });

    candleSeriesRef.current = candleSeries;

    const mockData = generateMockData();
    candleSeries.setData(mockData);

    // Add VWAP line
    if (vwap) {
      const vwapSeries = chart.addSeries(LineSeries, {
        color: "hsl(213, 94%, 58%)",
        lineWidth: 2,
        title: "VWAP",
      });
      vwapSeriesRef.current = vwapSeries;

      const vwapData = mockData.map(d => ({
        time: d.time,
        value: vwap + (Math.random() - 0.5) * 0.1,
      }));
      vwapSeries.setData(vwapData);
    }

    // Add key level price lines
    if (levelsData && currentPrice) {
      const levels = [
        { name: "PDH", price: levelsData.prev_day_high, color: "hsl(0, 72%, 51%)" },
        { name: "PDL", price: levelsData.prev_day_low, color: "hsl(142, 76%, 36%)" },
        { name: "ORH", price: levelsData.orh_5m, color: "hsl(0, 72%, 51%)" },
        { name: "ORL", price: levelsData.orl_5m, color: "hsl(142, 76%, 36%)" },
      ];

      levels.forEach(level => {
        // Calculate distance from current price
        const pctDist = Math.abs((level.price - currentPrice) / currentPrice) * 100;
        const isNear = pctDist <= 0.3; // Within 0.3%
        
        // Only show levels within 2% of current price
        if (pctDist < 2) {
          const isResistance = level.price > currentPrice;
          const label = isNear 
            ? `${level.name} ${isResistance ? '(RESISTANCE)' : '(SUPPORT)'}` 
            : level.name;
          
          candleSeries.createPriceLine({
            price: level.price,
            color: level.color,
            lineWidth: isNear ? 2 : 1,
            lineStyle: 2, // dashed
            axisLabelVisible: true,
            title: label,
          });
        }
      });
    }

    // Add ATR bands if available
    if (atr && currentPrice) {
      candleSeries.createPriceLine({
        price: currentPrice + atr,
        color: "hsl(215, 16%, 65%)",
        lineWidth: 1,
        lineStyle: 3, // dotted
        axisLabelVisible: true,
        title: "+1 ATR",
      });

      candleSeries.createPriceLine({
        price: currentPrice - atr,
        color: "hsl(215, 16%, 65%)",
        lineWidth: 1,
        lineStyle: 3, // dotted
        axisLabelVisible: true,
        title: "-1 ATR",
      });
    }

    chart.timeScale().fitContent();

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [symbol, levelsData, currentPrice, vwap, atr, loading]);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Execution Chart</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[400px] w-full" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Execution Chart - 1 Minute</CardTitle>
      </CardHeader>
      <CardContent>
        <div ref={chartContainerRef} className="w-full" />
      </CardContent>
    </Card>
  );
};
