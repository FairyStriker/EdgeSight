export interface DetectedObject {
  id: number;
  label: string;
  confidence: number;
  bbox: [number, number, number, number];
}

export interface StatusMeta {
  timestamp: string;
  fps: number;
  count: number;
  objects: DetectedObject[];
  seq?: number;
}

/** 채널별 메타데이터 묶음 — WebSocket /ws/status 가 보내는 형태. */
export interface MultiChannelStatus {
  channels: Record<number, StatusMeta>;
}

export type InputSource = "rtsp" | "usb" | "video";

/** 채널 1개 = 1개의 입력 소스 + 1개의 출력 스트림.
 *  ChannelGrid 가 channel 리스트를 받아 ChannelTile 로 렌더한다. */
export interface Channel {
  id: number;
  name: string;
  input_source: InputSource;
  /** RTSP URL 또는 USB 장치 경로(예: /dev/video0). video 모드에서는 빈 문자열. */
  source_uri: string;
  /** input_source === "video" 일 때 사용할 파일명. */
  video_filename: string | null;
  enabled: boolean;
  position: number;
}

export interface ChannelListResponse {
  channels: Channel[];
  /** 서버가 허용하는 최대 채널 수 (기본 8). 프론트의 +채널 버튼 비활성 기준. */
  max_channels: number;
}

/** input_source 관련 필드는 Channel 로 이전됨 — SystemConfig 는 전역 설정만 남는다. */
export interface SystemConfigDTO {
  conf_threshold: number;
  iou_threshold: number;
  server_port: number;
  language: "ko" | "en";
  active_model_id: number | null;
}

export interface DemoVideoItem {
  id: number;
  filename: string;
  uploaded_at: string;
}

export interface DemoVideoListResponse {
  videos: DemoVideoItem[];
}

export interface ModelItem {
  id: number;
  filename: string;
  uploaded_at: string;
}

export interface ModelListResponse {
  active_model_id: number | null;
  models: ModelItem[];
}

export type Lang = "ko" | "en";

export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface Job {
  id: string;
  type: string;
  filename: string;
  status: JobStatus;
  progress: number;
  message: string;
  error: string | null;
  model_id: number | null;
  created_at: number;
  completed_at: number | null;
}

export interface JobListResponse {
  jobs: Job[];
}
