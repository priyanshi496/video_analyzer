import { api } from './api';

export const projectService = {
  async getProjects() {
    // Currently, backend might not have a GET /api/v1/projects endpoint if it wasn't added.
    // If it exists, it returns list of projects for the user.
    // Since backend/app/api/routes/projects.py only has POST / and PATCH /{id}, we might need to mock or add it.
    // Assuming backend has GET /projects/ or we'll return an empty list for now if it fails.
    try {
      const response = await api.get('/projects/');
      return response.data;
    } catch (error: any) {
      if (error.response?.status === 404 || error.response?.status === 405) {
        return [];
      }
      throw error;
    }
  },

  async createProject(name: string = '') {
    const response = await api.post('/projects/', { name });
    return response.data;
  },

  async getProject(id: string) {
    const response = await api.get(`/projects/${id}`);
    return response.data;
  },

  async uploadMedia(projectId: string, files: File[]) {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    
    const response = await api.post(`/projects/${projectId}/media`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  async listMedia(projectId: string) {
    const response = await api.get(`/projects/${projectId}/media`);
    return response.data;
  },
  
  async startAnalysis(projectId: string, payload: any) {
    const response = await api.post(`/projects/${projectId}/analyze`, payload);
    return response.data;
  },

  async getJobStatus(jobId: string) {
    const response = await api.get(`/jobs/${jobId}`);
    return response.data;
  },

  async getLatestJob(projectId: string) {
    const response = await api.get(`/projects/${projectId}/jobs/latest`);
    return response.data;
  },

  async confirmStory(jobId: string, payload: any) {
    const response = await api.post(`/jobs/${jobId}/confirm-story`, payload);
    return response.data;
  }
};
