import { api } from './api';

export interface PodcastAnalyzeRequest {
  caption_style: 'word_by_word' | 'line_by_line';
  words_per_line: number;
  zoom_detection: 'auto_llm' | 'manual';
  zoom_intensity: number;
  caption_position: 'bottom' | 'top' | 'center';
  font_size: number;
  font_color: string;
}

export interface WordTimestamp {
  word: string;
  start: number;
  end: number;
  confidence?: number;
}

export interface CaptionSegment {
  text: string;
  start_time: number;
  end_time: number;
  duration: number;
}

export interface ImportantMoment {
  start_time: number;
  end_time: number;
  text: string;
  reason: string;
  intensity: 'low' | 'medium' | 'high';
  keywords: string[];
}

export interface ZoomEffect {
  start_time: number;
  end_time: number;
  zoom_start: number;
  zoom_end: number;
  transition_type: 'zoom_in' | 'hold' | 'zoom_out';
  reason: string;
}

export interface PodcastTimeline {
  job_id: string;
  final_video_url: string | null;
  transcript: {
    text: string;
    language: string;
    duration: number;
    words: WordTimestamp[];
  };
  caption_segments: CaptionSegment[];
  important_moments: ImportantMoment[];
  zoom_effects: ZoomEffect[];
}

export const podcastService = {
  async startProcessing(projectId: string, options: PodcastAnalyzeRequest) {
    const response = await api.post(`/projects/${projectId}/analyze-podcast`, options);
    return response.data;
  },

  async getTimeline(projectId: string): Promise<PodcastTimeline> {
    const response = await api.get(`/projects/${projectId}/podcast-timeline`);
    return response.data;
  },

  async getTranscript(jobId: string) {
    const response = await api.get(`/jobs/${jobId}/transcript`);
    return response.data;
  },

  async regenerateCaptions(jobId: string, options: PodcastAnalyzeRequest) {
    const response = await api.post(`/jobs/${jobId}/regenerate-captions`, options);
    return response.data;
  },
};
