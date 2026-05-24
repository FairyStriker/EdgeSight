import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Job } from "../api/types";

/**
 * 작업 목록 폴링 훅.
 * 진행 중 작업이 있으면 1초마다, 없으면 5초마다 갱신.
 */
export function useJobs(enabled: boolean) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const fetchOnce = useCallback(async () => {
    try {
      const r = await api.listJobs();
      setJobs(r.jobs);
      setError(null);
      return r.jobs;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;

    const tick = async () => {
      if (stopped) return;
      const list = await fetchOnce();
      const hasActive =
        list?.some(
          (j) => j.status === "pending" || j.status === "running"
        ) ?? false;
      if (!stopped) {
        timerRef.current = window.setTimeout(tick, hasActive ? 1000 : 5000);
      }
    };

    tick();

    return () => {
      stopped = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [enabled, fetchOnce]);

  return { jobs, error, reload: fetchOnce };
}
