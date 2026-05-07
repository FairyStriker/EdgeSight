import type {
  Job,
  JobListResponse,
  ModelListResponse,
  SystemConfigDTO,
} from "./types";

const TOKEN_KEY = "edgesight.token";

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

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  async getConfig(): Promise<SystemConfigDTO> {
    const res = await fetch("/api/config");
    return jsonOrThrow<SystemConfigDTO>(res);
  },

  async updateConfig(form: FormData): Promise<void> {
    const res = await fetch("/api/config/update", {
      method: "POST",
      body: form,
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
  },

  async listModels(): Promise<ModelListResponse> {
    const res = await fetch("/api/model/list");
    return jsonOrThrow<ModelListResponse>(res);
  },

  async uploadModel(file: File, classNames: string): Promise<void> {
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

  async uploadPt(
    file: File,
    imgsz: number = 640
  ): Promise<{ job_id: string }> {
    // .pt는 메타데이터에서 클래스 자동 추출하므로 class_names 미전송
    const fd = new FormData();
    fd.append("file", file);
    fd.append("imgsz", String(imgsz));
    const res = await fetch("/api/model/upload_pt", {
      method: "POST",
      body: fd,
      headers: authHeaders(),
    });
    return jsonOrThrow<{ job_id: string }>(res);
  },

  async listJobs(): Promise<JobListResponse> {
    const res = await fetch("/api/jobs");
    return jsonOrThrow<JobListResponse>(res);
  },

  async getJob(id: string): Promise<Job> {
    const res = await fetch(`/api/jobs/${id}`);
    return jsonOrThrow<Job>(res);
  },

  async selectModel(id: number): Promise<void> {
    const res = await fetch(`/api/model/select/${id}`, {
      method: "POST",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
  },

  async deleteModel(id: number): Promise<void> {
    const res = await fetch(`/api/model/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
  },
};
