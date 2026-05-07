import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { ModelListResponse } from "../api/types";

export function useModels(enabled: boolean) {
  const [data, setData] = useState<ModelListResponse>({
    active_model_id: null,
    models: [],
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.listModels();
      setData(r);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (enabled) reload();
  }, [enabled, reload]);

  return { ...data, loading, error, reload };
}
