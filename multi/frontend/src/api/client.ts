import type {
  Channel,
  ChannelListResponse,
  DemoVideoListResponse,
  Job,
  JobListResponse,
  ModelListResponse,
  SystemConfigDTO,
} from "./types";
import { mockApi } from "./mock";

const TOKEN_KEY = "edgesight.token";

/** Vite 환경변수 — `npm run dev:mock` 으로 켜면 모든 fetch 가 mock 으로 라우팅. */
export const USE_MOCK: boolean = import.meta.env.VITE_USE_MOCK === "true";

export const tokenStore = {
  get(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  },
  set(token: string) {
    localStorage.setItem(TOKEN_KEY, token);
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY);
  },
};

function authHeaders(): HeadersInit {
  const tok = tokenStore.get();
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

function jsonHeaders(): HeadersInit {
  return { "Content-Type": "application/json", ...authHeaders() };
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // ----- 시스템 설정 -----
  async getConfig(): Promise<SystemConfigDTO> {
    if (USE_MOCK) return mockApi.getConfig();
    return jsonOrThrow<SystemConfigDTO>(await fetch("/api/config"));
  },
  async updateConfig(form: FormData): Promise<void> {
    if (USE_MOCK) return mockApi.updateConfig(form);
    const res = await fetch("/api/config/update", {
      method: "POST",
      body: form,
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
  },

  // ----- 채널 CRUD -----
  async listChannels(): Promise<ChannelListResponse> {
    if (USE_MOCK) return mockApi.listChannels();
    return jsonOrThrow<ChannelListResponse>(await fetch("/api/channels"));
  },
  async createChannel(input: Omit<Channel, "id" | "position">): Promise<Channel> {
    if (USE_MOCK) return mockApi.createChannel(input);
    return jsonOrThrow<Channel>(
      await fetch("/api/channels", {
        method: "POST",
        body: JSON.stringify(input),
        headers: jsonHeaders(),
      })
    );
  },
  async updateChannel(
    id: number,
    patch: Partial<Omit<Channel, "id">>
  ): Promise<Channel> {
    if (USE_MOCK) return mockApi.updateChannel(id, patch);
    return jsonOrThrow<Channel>(
      await fetch(`/api/channels/${id}`, {
        method: "PUT",
        body: JSON.stringify(patch),
        headers: jsonHeaders(),
      })
    );
  },
  async deleteChannel(id: number): Promise<void> {
    if (USE_MOCK) return mockApi.deleteChannel(id);
    const res = await fetch(`/api/channels/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
  },
  async reorderChannels(ids: number[]): Promise<void> {
    if (USE_MOCK) return mockApi.reorderChannels(ids);
    const res = await fetch("/api/channels/reorder", {
      method: "POST",
      body: JSON.stringify({ ids }),
      headers: jsonHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
  },

  // ----- 모델 -----
  async listModels(): Promise<ModelListResponse> {
    if (USE_MOCK) return mockApi.listModels();
    return jsonOrThrow<ModelListResponse>(await fetch("/api/model/list"));
  },
  async uploadModel(file: File, classNames: string): Promise<void> {
    if (USE_MOCK) return mockApi.uploadModel(file, classNames);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("class_names", classNames);
    const res = await fetch("/api/model/upload", {
      method: "POST",
      body: fd,
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
  },
  async uploadPt(file: File, imgsz: number = 640): Promise<{ job_id: string }> {
    if (USE_MOCK) return mockApi.uploadPt(file, imgsz);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("imgsz", String(imgsz));
    return jsonOrThrow<{ job_id: string }>(
      await fetch("/api/model/upload_pt", {
        method: "POST",
        body: fd,
        headers: authHeaders(),
      })
    );
  },
  async selectModel(id: number): Promise<void> {
    if (USE_MOCK) return mockApi.selectModel(id);
    const res = await fetch(`/api/model/select/${id}`, {
      method: "POST",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
  },
  async deleteModel(id: number): Promise<void> {
    if (USE_MOCK) return mockApi.deleteModel(id);
    const res = await fetch(`/api/model/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
  },

  // ----- 작업 -----
  async listJobs(): Promise<JobListResponse> {
    if (USE_MOCK) return mockApi.listJobs();
    return jsonOrThrow<JobListResponse>(await fetch("/api/jobs"));
  },
  async getJob(id: string): Promise<Job> {
    if (USE_MOCK) return mockApi.getJob(id);
    return jsonOrThrow<Job>(await fetch(`/api/jobs/${id}`));
  },

  // ----- 영상 -----
  async listVideos(): Promise<DemoVideoListResponse> {
    if (USE_MOCK) return mockApi.listVideos();
    return jsonOrThrow<DemoVideoListResponse>(await fetch("/api/video/list"));
  },
  async uploadVideo(file: File): Promise<{ job_id: string }> {
    if (USE_MOCK) return mockApi.uploadVideo(file);
    const fd = new FormData();
    fd.append("file", file);
    return jsonOrThrow<{ job_id: string }>(
      await fetch("/api/video/upload", {
        method: "POST",
        body: fd,
        headers: authHeaders(),
      })
    );
  },
  async deleteVideo(id: number): Promise<void> {
    if (USE_MOCK) return mockApi.deleteVideo(id);
    const res = await fetch(`/api/video/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
  },
};
