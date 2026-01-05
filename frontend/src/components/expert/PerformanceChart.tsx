import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { TrendingUp } from "lucide-react";

interface PerformanceChartProps {
  data?: Array<{
    date: string;
    winRate: number;
    avgRR: number;
  }>;
  loading?: boolean;
}

// Mock data for demonstration - showing last 30 days
const generateMockData = () => {
  const data = [];
  const today = new Date();
  
  for (let i = 29; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);
    
    // Simulate trending performance with some variance
    const baseWinRate = 65 + (29 - i) * 0.3 + Math.random() * 5;
    const baseRR = 1.8 + (29 - i) * 0.02 + Math.random() * 0.3;
    
    data.push({
      date: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      winRate: Math.min(Math.max(baseWinRate, 45), 85),
      avgRR: Math.min(Math.max(baseRR, 1.2), 3.0),
    });
  }
  
  return data;
};

const mockData = generateMockData();

export function PerformanceChart({
  data = mockData,
  loading = false,
}: PerformanceChartProps) {
  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <TrendingUp className="h-5 w-5" />
            Performance Trends
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64 animate-pulse bg-muted rounded" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-primary" />
          Performance Trends (30 Days)
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart
            data={data}
            margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis
              dataKey="date"
              tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
              tickLine={{ stroke: 'hsl(var(--border))' }}
            />
            <YAxis
              yAxisId="left"
              domain={[0, 100]}
              tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
              tickLine={{ stroke: 'hsl(var(--border))' }}
              label={{
                value: 'Win Rate (%)',
                angle: -90,
                position: 'insideLeft',
                style: { fill: 'hsl(var(--muted-foreground))', fontSize: 11 }
              }}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={[0, 4]}
              tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
              tickLine={{ stroke: 'hsl(var(--border))' }}
              label={{
                value: 'Avg R:R',
                angle: 90,
                position: 'insideRight',
                style: { fill: 'hsl(var(--muted-foreground))', fontSize: 11 }
              }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: 'hsl(var(--background))',
                border: '1px solid hsl(var(--border))',
                borderRadius: '6px',
                fontSize: '12px'
              }}
              formatter={(value: number, name: string) => {
                if (name === 'winRate') return [`${value.toFixed(1)}%`, 'Win Rate'];
                if (name === 'avgRR') return [`1:${value.toFixed(1)}`, 'Avg R:R'];
                return [value, name];
              }}
            />
            <Legend
              wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }}
              formatter={(value) => {
                if (value === 'winRate') return 'Win Rate';
                if (value === 'avgRR') return 'Avg R:R';
                return value;
              }}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="winRate"
              stroke="#16a34a"
              strokeWidth={2}
              dot={{ fill: '#16a34a', r: 3 }}
              activeDot={{ r: 5 }}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="avgRR"
              stroke="#2563eb"
              strokeWidth={2}
              dot={{ fill: '#2563eb', r: 3 }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
