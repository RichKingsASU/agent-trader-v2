import { useCallback, useSyncExternalStore } from 'react';

export type LogLevel = 'info' | 'warn' | 'error' | 'debug';
export type LogSource = 'supabase' | 'alpaca' | 'exchange' | 'system' | 'ui';

export interface EventLog {
  id: string;
  timestamp: Date;
  level: LogLevel;
  source: LogSource;
  category: string;
  message: string;
  meta?: Record<string, unknown>;
}

export interface PersistenceStatus {
  enabled: boolean;
  lastFlushTime: Date | null;
  lastError: string | null;
  pendingCount: number;
}

const MAX_LOGS = 500;
const FLUSH_INTERVAL_MS = 1000;

declare global {
  interface Window {
    __OPS_LOG_INGEST_URL__?: string;
  }
}

function getConfiguredIngestUrl(): string | null {
  // Prefer a runtime-injected config if present (e.g., set by deployment).
  const fromWindow = typeof window !== 'undefined' ? window.__OPS_LOG_INGEST_URL__ : undefined;
  if (typeof fromWindow === 'string' && fromWindow.trim()) return fromWindow.trim();

  // Fallback to localStorage for local/dev usage.
  try {
    const fromStorage = localStorage.getItem('ops_log_ingest_url');
    return fromStorage?.trim() ? fromStorage.trim() : null;
  } catch {
    return null;
  }
}

// In-memory store
let logs: EventLog[] = [];
let listeners: Set<() => void> = new Set();

// Persistence state (optional)
let isPersistenceEnabled = false;
let opsToken: string | null = null;
let lastFlushTime: Date | null = null;
let lastError: string | null = null;
let pendingLogs: EventLog[] = [];
let persistenceSnapshot: PersistenceStatus = {
  enabled: false,
  lastFlushTime: null,
  lastError: null,
  pendingCount: 0,
};
let flushIntervalId: number | null = null;
let persistenceListeners: Set<() => void> = new Set();

const notifyListeners = () => {
  listeners.forEach((listener) => listener());
};

const updatePersistenceSnapshot = () => {
  persistenceSnapshot = {
    enabled: isPersistenceEnabled,
    lastFlushTime,
    lastError,
    pendingCount: pendingLogs.length,
  };
};

const notifyPersistenceListeners = () => {
  updatePersistenceSnapshot();
  persistenceListeners.forEach((listener) => listener());
};

async function flushLogs() {
  if (pendingLogs.length === 0 || !opsToken) return;

  const ingestUrl = getConfiguredIngestUrl();
  if (!ingestUrl) {
    lastError = 'No OPS log ingest URL configured';
    notifyPersistenceListeners();
    return;
  }

  const logsToFlush = [...pendingLogs];
  pendingLogs = [];
  notifyPersistenceListeners();

  try {
    const payload = logsToFlush.map((log) => ({
      source: log.source,
      level: log.level,
      event_type: log.category,
      message: log.message,
      meta: log.meta || {},
    }));

    const response = await fetch(ingestUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-OPS-TOKEN': opsToken,
      },
      body: JSON.stringify({ logs: payload }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error((errorData as any)?.error || `HTTP ${response.status}`);
    }

    lastFlushTime = new Date();
    lastError = null;
    notifyPersistenceListeners();
  } catch (error) {
    lastError = error instanceof Error ? error.message : 'Unknown error';
    pendingLogs = [...logsToFlush, ...pendingLogs];
    notifyPersistenceListeners();
    // eslint-disable-next-line no-console
    console.error('[eventLogStore] Failed to flush logs:', error);
  }
}

const startFlushInterval = () => {
  if (flushIntervalId) return;
  flushIntervalId = window.setInterval(flushLogs, FLUSH_INTERVAL_MS);
};

const stopFlushInterval = () => {
  if (flushIntervalId) {
    window.clearInterval(flushIntervalId);
    flushIntervalId = null;
  }
};

export const eventLogStore = {
  getSnapshot: () => logs,

  subscribe: (listener: () => void) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },

  logEvent: (level: LogLevel, source: LogSource, category: string, message: string, meta?: Record<string, unknown>) => {
    const newLog: EventLog = {
      id: crypto.randomUUID(),
      timestamp: new Date(),
      level,
      source,
      category,
      message,
      meta,
    };

    logs = [...logs.slice(-(MAX_LOGS - 1)), newLog];
    notifyListeners();

    if (isPersistenceEnabled && opsToken) {
      pendingLogs.push(newLog);
      notifyPersistenceListeners();
    }

    // Also log to browser console for debugging
    const prefix = `[${source}] [${category}]`;
    switch (level) {
      case 'error':
        // eslint-disable-next-line no-console
        console.error(prefix, message, meta || '');
        break;
      case 'warn':
        // eslint-disable-next-line no-console
        console.warn(prefix, message, meta || '');
        break;
      case 'debug':
        // eslint-disable-next-line no-console
        console.debug(prefix, message, meta || '');
        break;
      default:
        // eslint-disable-next-line no-console
        console.log(prefix, message, meta || '');
    }
  },

  clearLogs: () => {
    logs = [];
    notifyListeners();
  },
};

export const persistenceStore = {
  getSnapshot: (): PersistenceStatus => persistenceSnapshot,

  subscribe: (listener: () => void) => {
    persistenceListeners.add(listener);
    return () => persistenceListeners.delete(listener);
  },

  togglePersistence: (enabled: boolean, token?: string) => {
    isPersistenceEnabled = enabled;

    if (token) {
      opsToken = token;
      localStorage.setItem('ops_log_token', token);
    } else if (enabled && !opsToken) {
      opsToken = localStorage.getItem('ops_log_token');
    }

    if (enabled && opsToken) {
      startFlushInterval();
      lastError = getConfiguredIngestUrl() ? null : 'No OPS log ingest URL configured';
    } else {
      stopFlushInterval();
      if (!opsToken && enabled) lastError = 'No OPS token configured';
    }

    notifyPersistenceListeners();
    return opsToken !== null;
  },

  getStoredToken: (): string | null => {
    return localStorage.getItem('ops_log_token');
  },

  clearToken: () => {
    opsToken = null;
    localStorage.removeItem('ops_log_token');
    if (isPersistenceEnabled) {
      isPersistenceEnabled = false;
      stopFlushInterval();
    }
    notifyPersistenceListeners();
  },

  forceFlush: async () => {
    await flushLogs();
  },
};

export const useEventLogs = () =>
  useSyncExternalStore(eventLogStore.subscribe, eventLogStore.getSnapshot, eventLogStore.getSnapshot);

export const usePersistenceStatus = () =>
  useSyncExternalStore(persistenceStore.subscribe, persistenceStore.getSnapshot, persistenceStore.getSnapshot);

export const useEventLogger = () => {
  const logEvent = useCallback(
    (level: LogLevel, source: LogSource, category: string, message: string, meta?: Record<string, unknown>) => {
      eventLogStore.logEvent(level, source, category, message, meta);
    },
    []
  );
  return { logEvent };
};

export const logEvent = eventLogStore.logEvent;
export const clearLogs = eventLogStore.clearLogs;
export const togglePersistence = persistenceStore.togglePersistence;

