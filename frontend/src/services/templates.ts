import { api } from './api';

export interface SlotConfig {
  id: string;
  duration_seconds?: number;
  transition_out: string;
  deletable?: boolean;
  label?: string;
  text_overlay?: {
    placeholder: string;
    editable: boolean;
  };
}

export interface VideoTemplate {
  id: string;
  name: string;
  description: string;
  aspect_ratio: string;
  music_mode: string;
  music_query: string;
  slots: SlotConfig[];
  layout_mode?: string;
  sections?: any[];
  preview_url?: string;
}

export const templatesService = {
  async getTemplates(): Promise<VideoTemplate[]> {
    const response = await api.get('/templates/');
    return response.data;
  },

  async renderFromTemplate(
    projectId: string,
    templateId: string,
    slots: Array<{ slot_id: string; media_asset_id: string | null; text: string | null }>
  ) {
    const response = await api.post(`/templates/${projectId}/render`, {
      template_id: templateId,
      slots,
    });
    return response.data;
  },
};
export default templatesService;
