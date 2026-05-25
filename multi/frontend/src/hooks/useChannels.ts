import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Channel } from "../api/types";

interface UseChannelsResult {
  channels: Channel[];
  maxChannels: number;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  create: (input: Omit<Channel, "id" | "position">) => Promise<void>;
  update: (id: number, patch: Partial<Omit<Channel, "id">>) => Promise<void>;
  remove: (id: number) => Promise<void>;
}

export function useChannels(): UseChannelsResult {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [maxChannels, setMaxChannels] = useState(8);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.listChannels();
      const sorted = [...r.channels].sort((a, b) => a.position - b.position);
      setChannels(sorted);
      setMaxChannels(r.max_channels);
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

  const create = useCallback(
    async (input: Omit<Channel, "id" | "position">) => {
      await api.createChannel(input);
      await reload();
    },
    [reload]
  );

  const update = useCallback(
    async (id: number, patch: Partial<Omit<Channel, "id">>) => {
      await api.updateChannel(id, patch);
      await reload();
    },
    [reload]
  );

  const remove = useCallback(
    async (id: number) => {
      await api.deleteChannel(id);
      await reload();
    },
    [reload]
  );

  return { channels, maxChannels, loading, error, reload, create, update, remove };
}
