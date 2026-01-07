import React, { createContext, useContext, useState } from 'react';

export type StreamStatus = "disconnected" | "connecting" | "connected" | "paused" | "error";
export type StreamType = "price" | "options" | "news" | "level2" | "trades" | "account" | "quotes" | "other";

export interface DataStream {
  id: string;
  type: StreamType;
  status: StreamStatus;
  mps?: number; // messages per second
  lastMessageAt?: Date | null;
  error?: string | null;
  meta?: Record<string, unknown>;
}

// Simplified Bridge Context to stop the crashing
const DataStreamContext = createContext<any>(null);

export const useDataStreams = () => useContext(DataStreamContext) || { streams: [] };

export const DataStreamProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [streams, setStreams] = useState<any[]>([]);

  const registerStream = (stream: any) => {
    setStreams((prev) => [...prev, stream]);
  };

  const connectRealStream = () => {
    // Pre-Firebase stabilization: real WS plumbing is intentionally out of scope.
    return;
  };

  const getAggregateStats = () => ({
    totalStreams: streams.length,
    connected: streams.filter((s) => s?.status === 'connected').length,
    errors: streams.filter((s) => s?.status === 'error').length,
    totalMps: streams.reduce((sum, s) => sum + (typeof s?.mps === 'number' ? s.mps : 0), 0),
  });

  return (
    <DataStreamContext.Provider value={{ 
      streams,
      registerStream,
      connectRealStream,
      getAggregateStats
    }}>
      {children}
    </DataStreamContext.Provider>
  );
};
