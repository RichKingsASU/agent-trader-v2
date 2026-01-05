import { useEffect, useRef, useState } from "react";
import { createChart, ColorType, CandlestickSeries, LineSeries, HistogramSeries } from "lightweight-charts";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Settings } from "lucide-react";

interface CandleData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface KeyLevels {
  prev_day_high: number;
  prev_day_low: number;
  prev_day_close: number;
  premarket_high: number;
  premarket_low: number;
  open_price: number;
  orh_5m: number;
  orl_5m: number;
}

interface TradingViewChartProps {
  symbol: string;
  data?: CandleData[];
  levels?: KeyLevels;
  showCard?: boolean;
}

export function TradingViewChart({ symbol, data, levels, showCard = true }: TradingViewChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const candlestickSeriesRef = useRef<any>(null);
  const volumeSeriesRef = useRef<any>(null);
  const indicatorSeriesRef = useRef<Map<string, any>>(new Map());

  const [indicators, setIndicators] = useState({
    vwap: false,
    ema9: false,
    ema21: false,
    ema50: false,
    sma200: false,
    bb: false,
  });
  
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);

  const [showLevels, setShowLevels] = useState(true);

  // Mock key levels if not provided
  const mockLevels: KeyLevels = levels || {
    prev_day_high: 434.50,
    prev_day_low: 428.20,
    prev_day_close: 431.80,
    premarket_high: 432.90,
    premarket_low: 430.50,
    open_price: 431.20,
    orh_5m: 432.10,
    orl_5m: 430.80,
  };

  // Technical indicator calculations
  const calculateEMA = (data: number[], period: number): number[] => {
    const k = 2 / (period + 1);
    const emaData: number[] = [];
    emaData[0] = data[0];
    
    for (let i = 1; i < data.length; i++) {
      emaData[i] = data[i] * k + emaData[i - 1] * (1 - k);
    }
    return emaData;
  };

  const calculateSMA = (data: number[], period: number): number[] => {
    const smaData: number[] = [];
    for (let i = 0; i < data.length; i++) {
      if (i < period - 1) {
        smaData[i] = NaN;
      } else {
        const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0);
        smaData[i] = sum / period;
      }
    }
    return smaData;
  };

  const calculateVWAP = (candles: CandleData[]): number[] => {
    let cumulativeTPV = 0;
    let cumulativeVolume = 0;
    return candles.map(candle => {
      const typicalPrice = (candle.high + candle.low + candle.close) / 3;
      cumulativeTPV += typicalPrice * candle.volume;
      cumulativeVolume += candle.volume;
      return cumulativeTPV / cumulativeVolume;
    });
  };

  const calculateBollingerBands = (data: number[], period: number, stdDev: number) => {
    const sma = calculateSMA(data, period);
    const upper: number[] = [];
    const lower: number[] = [];
    
    for (let i = 0; i < data.length; i++) {
      if (i < period - 1) {
        upper[i] = NaN;
        lower[i] = NaN;
      } else {
        const slice = data.slice(i - period + 1, i + 1);
        const std = Math.sqrt(
          slice.reduce((sum, val) => sum + Math.pow(val - sma[i], 2), 0) / period
        );
        upper[i] = sma[i] + stdDev * std;
        lower[i] = sma[i] - stdDev * std;
      }
    }
    return { middle: sma, upper, lower };
  };

  // Generate mock intraday data if no data provided
  const mockData: CandleData[] = data || Array.from({ length: 100 }, (_, i) => {
    const timestamp = new Date();
    timestamp.setHours(9, 30, 0, 0); // Market open at 9:30 AM
    timestamp.setMinutes(timestamp.getMinutes() + i); // Add i minutes for each candle
    
    const basePrice = 432;
    const variation = Math.sin(i / 10) * 3;
    const open = basePrice + variation + (Math.random() - 0.5);
    const close = open + (Math.random() - 0.5) * 2;
    const high = Math.max(open, close) + Math.random() * 0.5;
    const low = Math.min(open, close) - Math.random() * 0.5;
    
    return {
      time: Math.floor(timestamp.getTime() / 1000) as any, // Unix timestamp in seconds
      open,
      high,
      low,
      close,
      volume: Math.floor(Math.random() * 100000) + 50000
    };
  });

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Get CSS variables for theming
    const styles = getComputedStyle(document.documentElement);
    const backgroundColor = styles.getPropertyValue('--background').trim();
    const textColor = styles.getPropertyValue('--foreground').trim();
    const gridColor = styles.getPropertyValue('--border').trim();

    // Create chart
    const chart: any = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: `hsl(${backgroundColor})` },
        textColor: `hsl(${textColor})`,
      },
      grid: {
        vertLines: { color: `hsl(${gridColor})` },
        horzLines: { color: `hsl(${gridColor})` },
      },
      width: chartContainerRef.current.clientWidth,
      height: 400,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: `hsl(${gridColor})`,
      },
      crosshair: {
        mode: 1,
      },
    });

    chartRef.current = chart;

    // Add candlestick series
    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: `hsl(${styles.getPropertyValue('--bull').trim()})`,
      downColor: `hsl(${styles.getPropertyValue('--bear').trim()})`,
      borderVisible: false,
      wickUpColor: `hsl(${styles.getPropertyValue('--bull').trim()})`,
      wickDownColor: `hsl(${styles.getPropertyValue('--bear').trim()})`,
    });

    candlestickSeriesRef.current = candlestickSeries;

    // Add volume series
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: `hsl(${styles.getPropertyValue('--muted-foreground').trim()})`,
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '',
    });

    volumeSeriesRef.current = volumeSeries;

    // Set data
    const chartData = mockData.map(d => ({
      time: d.time as any,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }));

    const volumeData = mockData.map(d => ({
      time: d.time as any,
      value: d.volume,
      color: d.close >= d.open 
        ? `hsl(${styles.getPropertyValue('--bull').trim()} / 0.5)`
        : `hsl(${styles.getPropertyValue('--bear').trim()} / 0.5)`,
    }));

    candlestickSeries.setData(chartData);
    volumeSeries.setData(volumeData);

    // Add key levels as price lines
    if (showLevels && mockLevels) {
      // Prev Day High/Low (red dotted)
      candlestickSeries.createPriceLine({
        price: mockLevels.prev_day_high,
        color: '#dc2626',
        lineWidth: 1,
        lineStyle: 3, // dotted
        axisLabelVisible: true,
        title: 'Prev High',
      });
      
      candlestickSeries.createPriceLine({
        price: mockLevels.prev_day_low,
        color: '#dc2626',
        lineWidth: 1,
        lineStyle: 3, // dotted
        axisLabelVisible: true,
        title: 'Prev Low',
      });

      // Premarket High/Low (blue dashed)
      candlestickSeries.createPriceLine({
        price: mockLevels.premarket_high,
        color: '#2563eb',
        lineWidth: 1,
        lineStyle: 2, // dashed
        axisLabelVisible: true,
        title: 'PM High',
      });
      
      candlestickSeries.createPriceLine({
        price: mockLevels.premarket_low,
        color: '#2563eb',
        lineWidth: 1,
        lineStyle: 2, // dashed
        axisLabelVisible: true,
        title: 'PM Low',
      });

      // ORH/ORL 5m (gray solid)
      candlestickSeries.createPriceLine({
        price: mockLevels.orh_5m,
        color: '#6b7280',
        lineWidth: 2,
        lineStyle: 0, // solid
        axisLabelVisible: true,
        title: 'ORH 5m',
      });
      
      candlestickSeries.createPriceLine({
        price: mockLevels.orl_5m,
        color: '#6b7280',
        lineWidth: 2,
        lineStyle: 0, // solid
        axisLabelVisible: true,
        title: 'ORL 5m',
      });
    }

    // Add technical indicators
    const closePrices = mockData.map(d => d.close);
    const times = mockData.map(d => d.time as any);

    // Clear existing indicator series safely
    indicatorSeriesRef.current.forEach(series => {
      if (series && chartRef.current) {
        try {
          chartRef.current.removeSeries(series);
        } catch (e) {
          // Series already removed or invalid
        }
      }
    });
    indicatorSeriesRef.current.clear();

    if (indicators.vwap) {
      const vwapValues = calculateVWAP(mockData);
      const vwapSeries = chart.addSeries(LineSeries, {
        color: '#2962FF',
        lineWidth: 2,
        title: 'VWAP',
      });
      vwapSeries.setData(vwapValues.map((value, i) => ({ time: times[i], value })));
      indicatorSeriesRef.current.set('vwap', vwapSeries);
    }

    if (indicators.ema9) {
      const ema9Values = calculateEMA(closePrices, 9);
      const ema9Series = chart.addSeries(LineSeries, {
        color: '#F23645',
        lineWidth: 1,
        title: 'EMA 9',
      });
      ema9Series.setData(ema9Values.map((value, i) => ({ time: times[i], value })));
      indicatorSeriesRef.current.set('ema9', ema9Series);
    }

    if (indicators.ema21) {
      const ema21Values = calculateEMA(closePrices, 21);
      const ema21Series = chart.addSeries(LineSeries, {
        color: '#FFA726',
        lineWidth: 1,
        title: 'EMA 21',
      });
      ema21Series.setData(ema21Values.map((value, i) => ({ time: times[i], value })));
      indicatorSeriesRef.current.set('ema21', ema21Series);
    }

    if (indicators.ema50) {
      const ema50Values = calculateEMA(closePrices, 50);
      const ema50Series = chart.addSeries(LineSeries, {
        color: '#26A69A',
        lineWidth: 1,
        title: 'EMA 50',
      });
      ema50Series.setData(ema50Values.map((value, i) => ({ time: times[i], value })));
      indicatorSeriesRef.current.set('ema50', ema50Series);
    }

    if (indicators.sma200) {
      const sma200Values = calculateSMA(closePrices, 200);
      const sma200Series = chart.addSeries(LineSeries, {
        color: '#AB47BC',
        lineWidth: 2,
        title: 'SMA 200',
      });
      sma200Series.setData(
        sma200Values
          .map((value, i) => ({ time: times[i], value }))
          .filter(d => !isNaN(d.value))
      );
      indicatorSeriesRef.current.set('sma200', sma200Series);
    }

    if (indicators.bb) {
      const bb = calculateBollingerBands(closePrices, 20, 2);
      
      const bbUpperSeries = chart.addSeries(LineSeries, {
        color: '#787B86',
        lineWidth: 1,
        lineStyle: 2,
        title: 'BB Upper',
      });
      bbUpperSeries.setData(
        bb.upper
          .map((value, i) => ({ time: times[i], value }))
          .filter(d => !isNaN(d.value))
      );
      
      const bbMiddleSeries = chart.addSeries(LineSeries, {
        color: '#787B86',
        lineWidth: 1,
        title: 'BB Middle',
      });
      bbMiddleSeries.setData(
        bb.middle
          .map((value, i) => ({ time: times[i], value }))
          .filter(d => !isNaN(d.value))
      );
      
      const bbLowerSeries = chart.addSeries(LineSeries, {
        color: '#787B86',
        lineWidth: 1,
        lineStyle: 2,
        title: 'BB Lower',
      });
      bbLowerSeries.setData(
        bb.lower
          .map((value, i) => ({ time: times[i], value }))
          .filter(d => !isNaN(d.value))
      );
      
      indicatorSeriesRef.current.set('bb-upper', bbUpperSeries);
      indicatorSeriesRef.current.set('bb-middle', bbMiddleSeries);
      indicatorSeriesRef.current.set('bb-lower', bbLowerSeries);
    }

    // Fit content
    chart.timeScale().fitContent();

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [symbol, indicators, showLevels]);

  const chartContent = (
    <div className="relative h-full">
      <div ref={chartContainerRef} className="h-full" />
      
      {/* Discrete Floating Indicator Button */}
      <Popover open={isPopoverOpen} onOpenChange={setIsPopoverOpen}>
        <PopoverTrigger asChild>
          <button
            className="absolute bottom-4 right-4 z-10 p-2.5 rounded-lg bg-background/60 backdrop-blur-md border border-white/10 opacity-60 hover:opacity-100 transition-all shadow-lg hover:shadow-xl"
            title="Indicators & Settings"
          >
            <Settings className="h-4 w-4 text-foreground" />
          </button>
        </PopoverTrigger>
        <PopoverContent 
          className="w-64 bg-background/95 backdrop-blur-md border-white/10 shadow-2xl"
          align="end"
          side="top"
        >
          <div className="space-y-3">
            <div className="pb-2 border-b border-white/10">
              <h4 className="text-xs font-bold uppercase tracking-wider text-foreground/70">
                Chart Controls
              </h4>
            </div>
            
            {/* Key Levels Toggle */}
            <div className="flex items-center justify-between">
              <Label htmlFor="levels" className="text-xs font-medium cursor-pointer">
                Key Levels
              </Label>
              <Checkbox
                id="levels"
                checked={showLevels}
                onCheckedChange={(checked) => setShowLevels(checked as boolean)}
              />
            </div>
            
            <div className="h-px bg-white/10" />
            
            {/* Technical Indicators */}
            <div className="space-y-2">
              <h5 className="text-xs font-bold uppercase tracking-wider text-foreground/50">
                Indicators
              </h5>
              
              <div className="flex items-center justify-between">
                <Label htmlFor="vwap" className="text-xs font-medium cursor-pointer">
                  VWAP
                </Label>
                <Checkbox
                  id="vwap"
                  checked={indicators.vwap}
                  onCheckedChange={(checked) => 
                    setIndicators(prev => ({ ...prev, vwap: checked as boolean }))
                  }
                />
              </div>
              
              <div className="flex items-center justify-between">
                <Label htmlFor="ema9" className="text-xs font-medium cursor-pointer">
                  EMA 9
                </Label>
                <Checkbox
                  id="ema9"
                  checked={indicators.ema9}
                  onCheckedChange={(checked) => 
                    setIndicators(prev => ({ ...prev, ema9: checked as boolean }))
                  }
                />
              </div>
              
              <div className="flex items-center justify-between">
                <Label htmlFor="ema21" className="text-xs font-medium cursor-pointer">
                  EMA 21
                </Label>
                <Checkbox
                  id="ema21"
                  checked={indicators.ema21}
                  onCheckedChange={(checked) => 
                    setIndicators(prev => ({ ...prev, ema21: checked as boolean }))
                  }
                />
              </div>
              
              <div className="flex items-center justify-between">
                <Label htmlFor="ema50" className="text-xs font-medium cursor-pointer">
                  EMA 50
                </Label>
                <Checkbox
                  id="ema50"
                  checked={indicators.ema50}
                  onCheckedChange={(checked) => 
                    setIndicators(prev => ({ ...prev, ema50: checked as boolean }))
                  }
                />
              </div>
              
              <div className="flex items-center justify-between">
                <Label htmlFor="sma200" className="text-xs font-medium cursor-pointer">
                  SMA 200
                </Label>
                <Checkbox
                  id="sma200"
                  checked={indicators.sma200}
                  onCheckedChange={(checked) => 
                    setIndicators(prev => ({ ...prev, sma200: checked as boolean }))
                  }
                />
              </div>
              
              <div className="flex items-center justify-between">
                <Label htmlFor="bb" className="text-xs font-medium cursor-pointer">
                  Bollinger Bands
                </Label>
                <Checkbox
                  id="bb"
                  checked={indicators.bb}
                  onCheckedChange={(checked) => 
                    setIndicators(prev => ({ ...prev, bb: checked as boolean }))
                  }
                />
              </div>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );

  return showCard ? <Card className="p-4 h-full">{chartContent}</Card> : chartContent;
}
