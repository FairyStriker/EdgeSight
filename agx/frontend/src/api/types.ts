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

export type InputSource = "rtsp" | "usb" | "video";

export interface SystemConfigDTO {
  rtsp_url: string;
  conf_threshold: number;
  iou_threshold: number;
  server_port: number;
  language: "ko" | "en";
  active_model_id: number | null;
  input_source: InputSource;
  video_filename: string | null;
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
