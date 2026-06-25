// Database Types
export interface Project {
  id: string;
  name: string;
  user_id: string;
  created_at: string;
  updated_at: string;
}

export interface MediaAsset {
  id: string;
  project_id: string;
  filename: string;
  object_key: string | null;
  is_image: boolean;
  sequence_index: number | null;
  file_size_bytes: number | null;
  presigned_url: string | null;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  created_at: string;
}

export type JobStatus = 'PENDING' | 'RUNNING' | 'STORY_PROPOSED' | 'COMPLETED' | 'FAILED';

export interface Job {
  id: string;
  project_id: string;
  status: JobStatus;
  progress: number;
  error_message: string | null;
  story_summary: string | null;
  final_video_url: string | null;
  vibe: string | null;
  music_mode: string | null;
  instrumental_only: boolean;
  directives: string | null;
  created_at: string;
  updated_at: string;
}

// UI Types
export type Vibe = 'cinematic' | 'fast-paced' | 'nostalgic' | 'hype' | 'peaceful' | 'dramatic';
export type MusicMode = 'ai-catalog' | 'suno-generation' | 'custom' | 'none';

export interface GenerationConfig {
  vibe: Vibe;
  musicMode: MusicMode;
  instrumentalOnly: boolean;
  directives: string;
}

// App State Types
export type AppScreen = 'dashboard' | 'workspace';

export interface UploadedFile {
  id: string;
  file: File;
  preview: string;
  progress: number;
  status: 'uploading' | 'uploaded' | 'error';
}
