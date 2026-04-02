export interface Video {
  id: string;
  title: string;
  url: string;
  duration: number;
  published_date?: string;
}

export interface TranscriptSegment {
  id: string;
  text: string;
  start_time: number;
  end_time: number;
  speaker?: string;
}

export interface Transcript {
  id: string;
  video_id: string;
  text: string;
  language: string;
  segments: TranscriptSegment[];
}

export interface Snapshot {
  id: string;
  video_id: string;
  image_url: string;
  timestamp: number;
  caption?: string;
}

export interface Document {
  id: string;
  job_id: string;
  content: string;
  format: 'markdown' | 'html' | 'pdf';
  created_at: string;
}

export type ProcessingJobStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface ProcessingJob {
  id: string;
  status: ProcessingJobStatus;
  video_url: string;
  video?: Video;
  transcript?: Transcript;
  snapshots?: Snapshot[];
  document?: Document;
  error?: string;
  created_at: string;
  updated_at: string;
}

export interface ApiResponse<T> {
  data: T;
  message?: string;
}

export interface ApiError {
  detail: string;
  status_code: number;
}
