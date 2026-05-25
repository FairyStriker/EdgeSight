import { useEffect, useRef, useState } from "react";
import type { MultiChannelStatus, StatusMeta } from "../api/types";
import { USE_MOCK } from "../api/client";
import { mockSubscribeStatus } from "../api/mock";

const EMPTY: MultiChannelStatus = { channels: {} };

const INITIAL_META: StatusMeta = {
  timestamp: "--:--:--",
  fps: 0,
  count: 0,
  objects: [],
};

/**
 * 채널별 실시간 메타데이터.
 *  - 실 모드: WebSocket /ws/status → `{channels: {id: meta}}` JSON.
 *  - mock 모드: setInterval 시뮬레이터.
 *
 * 백엔드는 변경된 채널만 보내거나 전체를 보낼 수 있으므로 항상 머지한다.
 */
export function useStatus(): MultiChannelStatus {
  const [status, setStatus] = useState<MultiChannelStatus>(EMPTY);
  const retryRef = useRef(0);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (USE_MOCK) {
      return mockSubscribeStatus(setStatus);
    }

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
          const data = JSON.parse(ev.data) as MultiChannelStatus;
          if (data && typeof data === "object" && data.channels) {
            setStatus((prev) => ({
              channels: { ...prev.channels, ...data.channels },
            }));
          }
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

/** 채널별 메타 추출 헬퍼. 해당 채널 데이터가 없으면 빈 메타 반환. */
export function getChannelMeta(
  status: MultiChannelStatus,
  channelId: number
): StatusMeta {
  return status.channels[channelId] ?? INITIAL_META;
}
