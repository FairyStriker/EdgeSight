import { useEffect, useRef, useState } from "react";
import type { StatusMeta } from "../api/types";

const INITIAL: StatusMeta = {
  timestamp: "--:--:--",
  fps: 0,
  count: 0,
  objects: [],
};

/**
 * WebSocket(/ws/status)으로 실시간 메타데이터 수신.
 * 연결 실패/끊김 시 지수 백오프로 자동 재연결.
 */
export function useStatus(): StatusMeta {
  const [status, setStatus] = useState<StatusMeta>(INITIAL);
  const retryRef = useRef(0);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    let closed = false;
    let ws: WebSocket | null = null;

    const connect = () => {
      if (closed) return;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const url = `${proto}://${window.location.host}/ws/status`;
      ws = new WebSocket(url);

      ws.onopen = () => {
        retryRef.current = 0;
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as StatusMeta;
          setStatus(data);
        } catch {
          /* ignore */
        }
      };
      ws.onclose = () => {
        if (closed) return;
        retryRef.current = Math.min(retryRef.current + 1, 6);
        const delay = Math.min(500 * 2 ** retryRef.current, 10000);
        timerRef.current = window.setTimeout(connect, delay);
      };
      ws.onerror = () => {
        ws?.close();
      };
    };

    connect();

    return () => {
      closed = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      ws?.close();
    };
  }, []);

  return status;
}
