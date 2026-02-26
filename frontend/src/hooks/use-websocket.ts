"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createWebSocket } from "@/lib/api";
import type { WSEventType } from "@/types/trading";

type EventHandler<T = unknown> = (data: T) => void;

interface UseWebSocketOptions {
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  reconnectDelay?: number;
}

export function useWebSocket(
  accountId: number | null,
  handlers: Partial<Record<WSEventType, EventHandler>>,
  options: UseWebSocketOptions = {},
) {
  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const { reconnectDelay = 3000 } = options;
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cleanedUpRef = useRef(false);

  const handlersRef = useRef(handlers);
  useEffect(() => { handlersRef.current = handlers; }, [handlers]);

  const optionsRef = useRef(options);
  useEffect(() => { optionsRef.current = options; }, [options]);

  const connect = useCallback(() => {
    if (!accountId) return;
    const ws = createWebSocket(accountId);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      optionsRef.current.onOpen?.();
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data as string);
        const handler = handlersRef.current[message.event as WSEventType];
        if (handler) handler(message.data);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      optionsRef.current.onClose?.();
      // Use connectRef so the reconnect always targets the CURRENT accountId,
      // not the stale one captured at ws creation time.
      if (!cleanedUpRef.current) {
        reconnectTimerRef.current = setTimeout(
          () => connectRef.current(),
          reconnectDelay,
        );
      }
    };

    ws.onerror = (error) => {
      optionsRef.current.onError?.(error);
      ws.close();
    };
  }, [accountId, reconnectDelay]);

  // Always keep a ref to the latest connect so onclose never uses a stale closure
  const connectRef = useRef(connect);
  useEffect(() => { connectRef.current = connect; }, [connect]);

  useEffect(() => {
    cleanedUpRef.current = false;
    connect();
    return () => {
      cleanedUpRef.current = true;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const disconnect = useCallback(() => {
    cleanedUpRef.current = true;
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    wsRef.current?.close();
  }, []);

  return { isConnected, send, disconnect };
}
