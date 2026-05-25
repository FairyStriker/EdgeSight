/**
 * Mock 데이터 어댑터 — 백엔드 없이 GUI 단독 동작용.
 * `VITE_USE_MOCK=true` 일 때 client.ts 가 이 모듈로 라우팅한다.
 *
 * 모킹 범위:
 *  - 채널 CRUD (in-memory)
 *  - 시스템 설정 (in-memory)
 *  - 모델/영상 리스트 (정적)
 *  - 채널별 메타 (객체 위치/개수 랜덤 워크)
 *  - 비디오 스트림: canvas 로 채널 ID/이름/박스 그린 데이터 URL
 *
 * 일부러 한 파일에 몰아넣었다 (백엔드 완성 후 한꺼번에 삭제하기 쉽도록).
 */

import type {
  Channel,
  ChannelListResponse,
  DemoVideoListResponse,
  Job,
  JobListResponse,
  ModelListResponse,
  MultiChannelStatus,
  StatusMeta,
  SystemConfigDTO,
} from "./types";

// ----- 상수 -----
export const MOCK_MAX_CHANNELS = 8;
const LABELS = ["person", "car", "bicycle", "dog", "truck", "bus"];

// ----- 초기 상태 (in-memory) -----
let _channels: Channel[] = [
  {
    id: 1,
    name: "Channel 1",
    input_source: "rtsp",
    source_uri: "rtsp://192.168.0.10:554/stream1",
    video_filename: null,
    enabled: true,
    position: 0,
  },
  {
    id: 2,
    name: "Channel 2",
    input_source: "rtsp",
    source_uri: "rtsp://192.168.0.11:554/stream1",
    video_filename: null,
    enabled: true,
    position: 1,
  },
];
let _nextChannelId = 3;

let _config: SystemConfigDTO = {
  conf_threshold: 0.25,
  iou_threshold: 0.45,
  server_port: 8000,
  language: "ko",
  active_model_id: 1,
};

const _models = [
  { id: 1, filename: "yolov8n.engine", uploaded_at: "2026-01-15 10:30" },
  { id: 2, filename: "yolov8s.engine", uploaded_at: "2026-02-03 14:12" },
];

const _videos = [
  { id: 1, filename: "demo_traffic.mp4", uploaded_at: "2026-01-20 09:00" },
];

// ----- 채널별 메타 시뮬레이터 -----
// 각 채널마다 0~6개의 객체를 가지고, 위치/개수가 천천히 변한다.
interface SimObj {
  id: number;
  label: string;
  cx: number;
  cy: number;
  vx: number;
  vy: number;
  w: number;
  h: number;
  confidence: number;
}
const _simState: Record<number, { objs: SimObj[]; nextId: number; fps: number }> = {};

function ensureSim(channelId: number) {
  if (!_simState[channelId]) {
    const count = 2 + Math.floor(Math.random() * 4);
    const objs: SimObj[] = [];
    for (let i = 0; i < count; i++) {
      objs.push(makeObj(i + 1));
    }
    _simState[channelId] = {
      objs,
      nextId: count + 1,
      fps: 28 + Math.random() * 4,
    };
  }
  return _simState[channelId];
}

function makeObj(id: number): SimObj {
  return {
    id,
    label: LABELS[Math.floor(Math.random() * LABELS.length)],
    cx: 100 + Math.random() * 1080,
    cy: 100 + Math.random() * 520,
    vx: (Math.random() - 0.5) * 8,
    vy: (Math.random() - 0.5) * 5,
    w: 60 + Math.random() * 120,
    h: 80 + Math.random() * 140,
    confidence: 0.55 + Math.random() * 0.4,
  };
}

function tickSim(channelId: number): StatusMeta {
  const s = ensureSim(channelId);
  // 객체 움직임
  for (const o of s.objs) {
    o.cx += o.vx;
    o.cy += o.vy;
    if (o.cx < 50 || o.cx > 1230) o.vx *= -1;
    if (o.cy < 50 || o.cy > 670) o.vy *= -1;
    o.confidence = Math.max(0.4, Math.min(0.99, o.confidence + (Math.random() - 0.5) * 0.04));
  }
  // 가끔 객체 추가/제거
  if (Math.random() < 0.02 && s.objs.length < 6) {
    s.objs.push(makeObj(s.nextId++));
  } else if (Math.random() < 0.02 && s.objs.length > 1) {
    s.objs.shift();
  }
  s.fps = Math.max(20, Math.min(32, s.fps + (Math.random() - 0.5) * 0.6));

  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");

  return {
    timestamp: `${hh}:${mm}:${ss}`,
    fps: s.fps,
    count: s.objs.length,
    objects: s.objs.map((o) => ({
      id: o.id,
      label: o.label,
      confidence: Math.round(o.confidence * 100) / 100,
      bbox: [
        Math.round(o.cx - o.w / 2),
        Math.round(o.cy - o.h / 2),
        Math.round(o.w),
        Math.round(o.h),
      ] as [number, number, number, number],
    })),
  };
}

// ----- 비디오 프레임 (canvas → data URL) -----
const CHANNEL_BG = [
  "#1e3a5f", "#5f1e3a", "#3a5f1e", "#5f3a1e",
  "#1e5f3a", "#3a1e5f", "#5f5f1e", "#1e5f5f",
];

export function mockFrameDataUrl(channel: Channel): string {
  const w = 640;
  const h = 360;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";

  const bg = CHANNEL_BG[(channel.id - 1) % CHANNEL_BG.length];
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);

  // 시뮬레이션 상태에서 박스 그리기 (해상도 1280x720 → 640x360 으로 축소)
  const sim = _simState[channel.id];
  if (sim) {
    for (const o of sim.objs) {
      const x = (o.cx - o.w / 2) * (w / 1280);
      const y = (o.cy - o.h / 2) * (h / 720);
      const bw = o.w * (w / 1280);
      const bh = o.h * (h / 720);
      ctx.strokeStyle = "#00ff88";
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, bw, bh);
      ctx.fillStyle = "rgba(0,0,0,0.6)";
      ctx.fillRect(x, y - 18, 80, 18);
      ctx.fillStyle = "#fff";
      ctx.font = "12px monospace";
      ctx.fillText(`${o.label} ${o.confidence.toFixed(2)}`, x + 4, y - 5);
    }
  }

  // 채널 라벨 (좌상단)
  ctx.fillStyle = "rgba(0,0,0,0.6)";
  ctx.fillRect(8, 8, 200, 28);
  ctx.fillStyle = "#fff";
  ctx.font = "bold 14px monospace";
  ctx.fillText(`[${channel.id}] ${channel.name}`, 16, 27);

  // 우상단: input source 배지
  const srcLabel = channel.input_source.toUpperCase();
  ctx.fillStyle = "rgba(220,53,69,0.85)";
  ctx.fillRect(w - 70, 8, 62, 22);
  ctx.fillStyle = "#fff";
  ctx.font = "bold 11px monospace";
  ctx.fillText(srcLabel, w - 63, 23);

  // 우하단: 시간 (캐시 회피)
  ctx.fillStyle = "rgba(0,0,0,0.6)";
  ctx.fillRect(w - 110, h - 30, 100, 22);
  ctx.fillStyle = "#fff";
  ctx.font = "12px monospace";
  ctx.fillText(new Date().toLocaleTimeString(), w - 102, h - 14);

  return canvas.toDataURL("image/jpeg", 0.7);
}

// ----- mock API 본체 -----
export const mockApi = {
  async getConfig(): Promise<SystemConfigDTO> {
    return { ..._config };
  },

  async updateConfig(form: FormData): Promise<void> {
    _config.conf_threshold = parseFloat(String(form.get("conf") ?? _config.conf_threshold));
    _config.iou_threshold = parseFloat(String(form.get("iou") ?? _config.iou_threshold));
    _config.server_port = parseInt(String(form.get("port") ?? _config.server_port), 10);
    _config.language = (form.get("language") as "ko" | "en") ?? _config.language;
  },

  async listChannels(): Promise<ChannelListResponse> {
    return { channels: [..._channels], max_channels: MOCK_MAX_CHANNELS };
  },

  async createChannel(input: Omit<Channel, "id" | "position">): Promise<Channel> {
    if (_channels.length >= MOCK_MAX_CHANNELS) {
      throw new Error(`최대 ${MOCK_MAX_CHANNELS}개 채널까지만 추가할 수 있습니다.`);
    }
    const ch: Channel = {
      ...input,
      id: _nextChannelId++,
      position: _channels.length,
    };
    _channels.push(ch);
    return ch;
  },

  async updateChannel(id: number, patch: Partial<Omit<Channel, "id">>): Promise<Channel> {
    const idx = _channels.findIndex((c) => c.id === id);
    if (idx < 0) throw new Error("채널을 찾을 수 없습니다.");
    _channels[idx] = { ..._channels[idx], ...patch };
    return _channels[idx];
  },

  async deleteChannel(id: number): Promise<void> {
    if (_channels.length <= 1) {
      throw new Error("채널은 최소 1개 이상 유지해야 합니다.");
    }
    _channels = _channels.filter((c) => c.id !== id);
    delete _simState[id];
    _channels.forEach((c, i) => (c.position = i));
  },

  async reorderChannels(ids: number[]): Promise<void> {
    const byId = new Map(_channels.map((c) => [c.id, c]));
    const reordered: Channel[] = [];
    ids.forEach((id, i) => {
      const c = byId.get(id);
      if (c) {
        c.position = i;
        reordered.push(c);
      }
    });
    if (reordered.length === _channels.length) _channels = reordered;
  },

  async listModels(): Promise<ModelListResponse> {
    return { active_model_id: _config.active_model_id, models: [..._models] };
  },

  async selectModel(id: number): Promise<void> {
    _config.active_model_id = id;
  },

  async deleteModel(_id: number): Promise<void> {
    /* no-op in mock */
  },

  async uploadModel(_file: File, _classNames: string): Promise<void> {
    /* no-op in mock */
  },

  async uploadPt(_file: File, _imgsz: number): Promise<{ job_id: string }> {
    return { job_id: "mock-job-" + Date.now() };
  },

  async listJobs(): Promise<JobListResponse> {
    return { jobs: [] };
  },

  async getJob(id: string): Promise<Job> {
    return {
      id,
      type: "mock",
      filename: "mock.pt",
      status: "completed",
      progress: 100,
      message: "(mock 모드 — 실제 변환 없음)",
      error: null,
      model_id: null,
      created_at: Date.now() / 1000,
      completed_at: Date.now() / 1000,
    };
  },

  async listVideos(): Promise<DemoVideoListResponse> {
    return { videos: [..._videos] };
  },

  async uploadVideo(_file: File): Promise<{ job_id: string }> {
    return { job_id: "mock-vid-" + Date.now() };
  },

  async deleteVideo(_id: number): Promise<void> {
    /* no-op */
  },
};

// ----- mock 메타 폴링 -----
// 진짜 WebSocket 대신 setInterval 로 채널별 메타 갱신 후 콜백.
type StatusListener = (status: MultiChannelStatus) => void;
const _listeners = new Set<StatusListener>();
let _tickerHandle: number | null = null;

function startTicker() {
  if (_tickerHandle != null) return;
  _tickerHandle = window.setInterval(() => {
    if (_listeners.size === 0) return;
    const channels: Record<number, StatusMeta> = {};
    for (const ch of _channels) {
      if (!ch.enabled) continue;
      channels[ch.id] = tickSim(ch.id);
    }
    const snapshot: MultiChannelStatus = { channels };
    for (const cb of _listeners) cb(snapshot);
  }, 100); // 10Hz
}

export function mockSubscribeStatus(cb: StatusListener): () => void {
  _listeners.add(cb);
  startTicker();
  return () => {
    _listeners.delete(cb);
  };
}

/** mock 채널 정보(VideoStream 프레임 생성용) 조회 헬퍼. */
export function mockGetChannel(id: number): Channel | undefined {
  return _channels.find((c) => c.id === id);
}
