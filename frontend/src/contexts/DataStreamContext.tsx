import React, { createContext, useContext, useState } from 'react';

// Simplified Bridge Context to stop the crashing
const DataStreamContext = createContext<any>(null);

export const useDataStreams = () => useContext(DataStreamContext) || { streams: [] };

export const DataStreamProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  return (
    <DataStreamContext.Provider value={{ 
      streams: [], 
      getAggregateStats: () => ({ totalStreams: 0, connected: 0, errors: 0, totalMps: 0 }) 
    }}>
      {children}
    </DataStreamContext.Provider>
  );
};
