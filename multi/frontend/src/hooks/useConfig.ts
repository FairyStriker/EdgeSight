import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { SystemConfigDTO } from "../api/types";

export function useConfig() {
  const [config, setConfig] = useState<SystemConfigDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const c = await api.getConfig();
      setConfig(c);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  return { config, loading, error, reload, setConfig };
}
