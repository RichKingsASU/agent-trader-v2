import { useEffect, useCallback, useRef } from 'react';
import { useDataStreams, StreamType, StreamStatus } from '@/contexts/DataStreamContext';
import wsManager, { WebSocketConfig, WebSocketStatus } from '@/services/WebSocketManager';

interface UseWebSocketStreamOptions {
  streamId: string;
  streamName: string;
  streamType: StreamType;
  exchange: string;
  symbols: string[];
  url: string;
  protocols?: string[];
  autoConnect?: boolean;
  onMessage?: (data: any) => void;
}

const mapWsStatusToStreamStatus = (status: WebSocketStatus): StreamStatus => {
  switch (status) {
    case 'connected': return 'connected';
    case 'connecting': return 'connecting';
    case 'disconnected': return 'disconnected';
    case 'error': return 'error';
    default: return 'disconnected';
  }
};

export const useWebSocketStream = ({
  streamId,
  streamName,
  streamType,
  exchange,
  symbols,
  url,
  protocols,
  autoConnect = true,
  onMessage
}: UseWebSocketStreamOptions) => {
  const { registerStream, unregisterStream, updateStreamStatus, recordMessage } = useDataStreams();
  const isRegisteredRef = useRef(false);
  const onMessageRef = useRef(onMessage);

  // Keep onMessage ref up to date
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  // Register stream on mount
  useEffect(() => {
    if (!isRegisteredRef.current) {
      registerStream({
        id: streamId,
        name: streamName,
        type: streamType,
        exchange,
        symbols,
        status: 'disconnected',
        lastMessage: null,
        latencyMs: 0,
        lastError: null,
        connectedAt: null
      });
      isRegisteredRef.current = true;
    }

    return () => {
      if (isRegisteredRef.current) {
        wsManager.disconnect(streamId);
        unregisterStream(streamId);
        isRegisteredRef.current = false;
      }
    };
  }, [streamId, streamName, streamType, exchange, symbols, registerStream, unregisterStream]);

  // Handle WebSocket connection
  useEffect(() => {
    if (!autoConnect) return;

    const config: WebSocketConfig = {
      url,
      protocols,
      reconnectInterval: 5000,
      maxReconnectAttempts: 10,
      heartbeatInterval: 30000
    };

    // Subscribe to status changes
    const unsubscribeStatus = wsManager.onStatusChange(streamId, (status, error) => {
      updateStreamStatus(streamId, mapWsStatusToStreamStatus(status), error);
    });

    // Subscribe to messages
    const unsubscribeMessage = wsManager.onMessage(streamId, (data, latencyMs) => {
      recordMessage(streamId, latencyMs);
      onMessageRef.current?.(data);
    });

    // Connect
    wsManager.connect(streamId, config);

    // Subscribe to symbols after connection
    const statusCheck = wsManager.onStatusChange(streamId, (status) => {
      if (status === 'connected' && symbols.length > 0) {
        wsManager.subscribe(streamId, symbols);
      }
    });

    return () => {
      unsubscribeStatus();
      unsubscribeMessage();
      statusCheck();
    };
  }, [streamId, url, protocols, autoConnect, symbols, updateStreamStatus, recordMessage]);

  const connect = useCallback(() => {
    const config: WebSocketConfig = {
      url,
      protocols,
      reconnectInterval: 5000,
      maxReconnectAttempts: 10
    };
    wsManager.connect(streamId, config);
  }, [streamId, url, protocols]);

  const disconnect = useCallback(() => {
    wsManager.disconnect(streamId);
  }, [streamId]);

  const reconnect = useCallback(() => {
    wsManager.reconnect(streamId);
  }, [streamId]);

  const send = useCallback((data: any) => {
    return wsManager.send(streamId, data);
  }, [streamId]);

  const subscribe = useCallback((newSymbols: string[]) => {
    return wsManager.subscribe(streamId, newSymbols);
  }, [streamId]);

  const unsubscribe = useCallback((symbolsToRemove: string[]) => {
    return wsManager.unsubscribe(streamId, symbolsToRemove);
  }, [streamId]);

  return {
    connect,
    disconnect,
    reconnect,
    send,
    subscribe,
    unsubscribe
  };
};
