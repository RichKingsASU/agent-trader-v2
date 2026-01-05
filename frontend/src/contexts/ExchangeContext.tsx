import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { getFirestore, onSnapshot, getDoc } from 'firebase/firestore';

import { useAuth } from '@/contexts/AuthContext';
import { tenantCollection, tenantDoc } from '@/lib/tenancy/firestore';


export type ExchangeType = 'broker' | 'data-provider' | 'options-exchange';
export type ExchangeStatus = 'active' | 'inactive' | 'degraded' | 'maintenance';
export type Capability = 'equities' | 'options' | 'futures' | 'crypto';

export interface RateLimits {
  requestsPerMinute: number;
  requestsUsed: number;
  resetTime: Date;
}

export interface Exchange {
  id: string;
  name: string;
  displayName: string;
  type: ExchangeType;
  status: ExchangeStatus;
  apiVersion: string;
  rateLimits: RateLimits;
  capabilities: Capability[];
  streams: string[];
  lastHealthCheck: Date;
  latencyMs: number;
  errorRate: number;
  isFromDatabase?: boolean;
  brokerAccountId?: string;
}

interface ExchangeContextType {
  exchanges: Exchange[];
  addExchange: (exchange: Exchange) => void;
  removeExchange: (id: string) => void;
  updateExchangeStatus: (id: string, status: ExchangeStatus, metadata?: { latencyMs?: number; streams?: string[]; errorRate?: number }) => void;
  updateRateLimits: (id: string, limits: Partial<RateLimits>) => void;
  testConnection: (id: string) => Promise<boolean>;
  getExchangeById: (id: string) => Exchange | undefined;
  getExchangesByType: (type: ExchangeType) => Exchange[];
  getOverallHealth: () => { healthy: number; degraded: number; down: number };
  isLoading: boolean;
}

const ExchangeContext = createContext<ExchangeContextType | null>(null);

export const useExchanges = () => {
  const context = useContext(ExchangeContext);
  if (!context) throw new Error('useExchanges must be used within ExchangeProvider');
  return context;
};

// Reference data providers (not from database)
const REFERENCE_PROVIDERS: Exchange[] = [
  {
    id: 'polygon',
    name: 'polygon',
    displayName: 'Polygon.io',
    type: 'data-provider',
    status: 'inactive',
    apiVersion: 'v3',
    rateLimits: { requestsPerMinute: 500, requestsUsed: 0, resetTime: new Date() },
    capabilities: ['equities', 'options', 'crypto'],
    streams: [],
    lastHealthCheck: new Date(),
    latencyMs: 0,
    errorRate: 0,
    isFromDatabase: false
  },
  {
    id: 'alpaca',
    name: 'alpaca',
    displayName: 'Alpaca Markets',
    type: 'data-provider',
    status: 'inactive',
    apiVersion: 'v2',
    rateLimits: { requestsPerMinute: 200, requestsUsed: 0, resetTime: new Date() },
    capabilities: ['equities', 'crypto'],
    streams: [],
    lastHealthCheck: new Date(),
    latencyMs: 0,
    errorRate: 0,
    isFromDatabase: false
  },
  {
    id: 'firestore',
    name: 'firestore',
    displayName: 'Firestore (Database)',
    type: 'data-provider',
    status: 'active',
    apiVersion: 'v9',
    rateLimits: { requestsPerMinute: 1000, requestsUsed: 0, resetTime: new Date() },
    capabilities: ['equities', 'options'],
    streams: ['firestore-market-data', 'firestore-quotes', 'firestore-news', 'firestore-options-flow'],
    lastHealthCheck: new Date(),
    latencyMs: 15,
    errorRate: 0,
    isFromDatabase: false
  }
];

export const ExchangeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [exchanges, setExchanges] = useState<Exchange[]>(REFERENCE_PROVIDERS);
  const [isLoading, setIsLoading] = useState(true);
  const { tenantId } = useAuth();

  // Load broker accounts from Firestore
  useEffect(() => {
    const db = getFirestore();
    if (!tenantId) {
      setExchanges(REFERENCE_PROVIDERS);
      setIsLoading(false);
      return;
    }

    const brokerAccountsCollection = tenantCollection(db, tenantId, 'broker_accounts');

    const unsubscribe = onSnapshot(brokerAccountsCollection, (snapshot) => {
      const brokerExchanges: Exchange[] = snapshot.docs.map(doc => {
        const account = doc.data();
        return {
          id: `broker-${doc.id}`,
          name: account.broker_name,
          displayName: `${account.broker_name.charAt(0).toUpperCase() + account.broker_name.slice(1)} ${account.is_paper_trading ? '(Paper)' : '(Live)'} - ${account.account_label}`,
          type: 'broker' as ExchangeType,
          status: 'active' as ExchangeStatus, // Assume active if in database
          apiVersion: 'v1',
          rateLimits: { 
            requestsPerMinute: 120, 
            requestsUsed: 0, 
            resetTime: new Date() 
          },
          capabilities: account.broker_name === 'tastytrade' 
            ? ['equities', 'options'] as Capability[]
            : ['equities', 'crypto'] as Capability[],
          streams: [],
          lastHealthCheck: new Date(account.updated_at.seconds * 1000),
          latencyMs: 0,
          errorRate: 0,
          isFromDatabase: true,
          brokerAccountId: doc.id
        };
      });

      // Combine database brokers with reference providers
      setExchanges([...brokerExchanges, ...REFERENCE_PROVIDERS]);
      setIsLoading(false);
    }, (error) => {
      console.error('Error loading broker accounts:', error);
      // Fall back to reference providers only
      setExchanges(REFERENCE_PROVIDERS);
      setIsLoading(false);
    });

    return () => unsubscribe();
  }, [tenantId]);

  // Periodic health check for Firestore connection
  useEffect(() => {
    const db = getFirestore();
    const checkHealth = async () => {
      if (!tenantId) return;
      const start = Date.now();
      try {
        await getDoc(tenantDoc(db, tenantId, 'live_quotes', 'SPY'));
        const latency = Date.now() - start;
        
        logEvent(
          'info',
          'exchange',
          'health',
          `Firestore health check: active`,
          { latencyMs: latency }
        );

        setExchanges(prev => prev.map(ex => {
          if (ex.id === 'firestore') {
            return {
              ...ex,
              status: 'active',
              lastHealthCheck: new Date(),
              latencyMs: latency,
              errorRate: 0
            };
          }
          return ex;
        }));
      } catch (error) {
        const latency = Date.now() - start;
        logEvent(
          'warn',
          'exchange',
          'health',
          `Firestore health check: degraded`,
          { latencyMs: latency, error: (error as Error).message }
        );
        setExchanges(prev => prev.map(ex => {
          if (ex.id === 'firestore') {
            return {
              ...ex,
              status: 'degraded',
              lastHealthCheck: new Date(),
              latencyMs: latency,
              errorRate: 0.1
            };
          }
          return ex;
        }));
      }
    };

    // Initial check
    checkHealth();
    
    // Then check every 30 seconds
    const interval = setInterval(checkHealth, 30000);

    return () => clearInterval(interval);
  }, [tenantId]);

  const addExchange = useCallback((exchange: Exchange) => {
    setExchanges(prev => [...prev, exchange]);
  }, []);

  const removeExchange = useCallback((id: string) => {
    // Don't allow removing database exchanges
    const exchange = exchanges.find(e => e.id === id);
    if (exchange?.isFromDatabase) return;
    
    setExchanges(prev => prev.filter(e => e.id !== id));
  }, [exchanges]);

  const updateExchangeStatus = useCallback((id: string, status: ExchangeStatus, metadata?: { latencyMs?: number; streams?: string[]; errorRate?: number }) => {
    setExchanges(prev => prev.map(e => e.id === id ? { 
      ...e, 
      status, 
      lastHealthCheck: new Date(),
      ...(metadata?.latencyMs !== undefined && { latencyMs: metadata.latencyMs }),
      ...(metadata?.streams && { streams: metadata.streams }),
      ...(metadata?.errorRate !== undefined && { errorRate: metadata.errorRate })
    } : e));
  }, []);

  const updateRateLimits = useCallback((id: string, limits: Partial<RateLimits>) => {
    setExchanges(prev => prev.map(e => 
      e.id === id ? { ...e, rateLimits: { ...e.rateLimits, ...limits } } : e
    ));
  }, []);

  const testConnection = useCallback(async (id: string): Promise<boolean> => {
    const exchange = exchanges.find(e => e.id === id);
    
    // For Firestore, actually test the connection
    if (exchange?.id === 'firestore') {
      setExchanges(prev => prev.map(e => 
        e.id === id ? { ...e, status: 'inactive' } : e
      ));
      
      const start = Date.now();
      try {
        const db = getFirestore();
        if (!tenantId) return false;
        await getDoc(tenantDoc(db, tenantId, 'live_quotes', 'SPY'));
        const latency = Date.now() - start;
        
        setExchanges(prev => prev.map(e => 
          e.id === id ? { 
            ...e, 
            status: 'active', 
            lastHealthCheck: new Date(),
            latencyMs: latency
          } : e
        ));
        return true;
      } catch (error) {
        setExchanges(prev => prev.map(e => 
          e.id === id ? { 
            ...e, 
            status: 'degraded', 
            lastHealthCheck: new Date(),
          } : e
        ));
        return false;
      }
    }

    // For database brokers, just verify the record exists
    if (exchange?.isFromDatabase && exchange.brokerAccountId) {
      try {
        const db = getFirestore();
        if (!tenantId) return false;
        const docRef = tenantDoc(db, tenantId, 'broker_accounts', exchange.brokerAccountId);
        const docSnap = await getDoc(docRef);
        const success = docSnap.exists();
        setExchanges(prev => prev.map(e => 
          e.id === id ? { 
            ...e, 
            status: success ? 'active' : 'inactive', 
            lastHealthCheck: new Date()
          } : e
        ));
        return success;
      } catch (error) {
        return false;
      }
    }

    // For reference providers, simulate connection test
    return new Promise(resolve => {
      setTimeout(() => {
        const success = Math.random() > 0.3; // 70% success rate for mock
        setExchanges(prev => prev.map(e => 
          e.id === id ? { ...e, status: success ? 'active' : 'inactive', lastHealthCheck: new Date() } : e
        ));
        resolve(success);
      }, 1000);
    });
  }, [exchanges, tenantId]);

  const getExchangeById = useCallback((id: string) => exchanges.find(e => e.id === id), [exchanges]);
  
  const getExchangesByType = useCallback((type: ExchangeType) => exchanges.filter(e => e.type === type), [exchanges]);

  const getOverallHealth = useCallback(() => ({
    healthy: exchanges.filter(e => e.status === 'active').length,
    degraded: exchanges.filter(e => e.status === 'degraded').length,
    down: exchanges.filter(e => e.status === 'inactive' || e.status === 'maintenance').length
  }), [exchanges]);

  return (
    <ExchangeContext.Provider value={{
      exchanges,
      addExchange,
      removeExchange,
      updateExchangeStatus,
      updateRateLimits,
      testConnection,
      getExchangeById,
      getExchangesByType,
      getOverallHealth,
      isLoading
    }}>
      {children}
    </ExchangeContext.Provider>
  );
};
