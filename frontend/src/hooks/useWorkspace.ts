import { useState, useEffect, useCallback } from 'react';
import { projectService } from '../services/projects';

export function useWorkspace(projectId: string) {
  const [project, setProject] = useState<any>(null);
  const [mediaAssets, setMediaAssets] = useState<any[]>([]);
  const [job, setJob] = useState<any>(null);
  const [jobHistory, setJobHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);

  const fetchData = useCallback(async () => {
    if (!projectId) return;
    try {
      setLoading(true);
      const p = await projectService.getProject(projectId);
      setProject(p);
      const m = await projectService.listMedia(projectId);
      setMediaAssets(m || []);
      
      const history = await projectService.listJobs(projectId);
      setJobHistory(history || []);
      
      try {
        const latestJob = await projectService.getLatestJob(projectId);
        // Automatically resume job if it's pending, running, completed, or story proposed
        if (latestJob && latestJob.status !== 'FAILED') {
          setJob(latestJob);
        }
      } catch (err: any) {
        // 404 is expected if there are no jobs yet
      }
    } catch (e) {
      console.error('Failed to fetch workspace data:', e);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Polling Job Status
  useEffect(() => {
    let interval: any;
    if (job?.id && job.status !== 'COMPLETED' && job.status !== 'FAILED') {
      interval = setInterval(async () => {
        try {
          const status = await projectService.getJobStatus(job.id);
          setJob(status);
        } catch (e) {
          console.error("Failed to poll status", e);
        }
      }, 3000);
    }
    return () => clearInterval(interval);
  }, [job?.id, job?.status]);

  const uploadFile = async (file: File) => {
    setUploading(true);
    try {
      await projectService.uploadMedia(projectId, [file]);
      // Refetch media
      const m = await projectService.listMedia(projectId);
      setMediaAssets(m || []);
    } catch (err) {
      console.error(err);
      alert('Failed to upload file.');
    } finally {
      setUploading(false);
    }
  };

  const deleteAsset = async (_assetId: string) => {
    // Optional functionality - skip if backend doesn't support it yet
    console.warn('Delete media not implemented on backend');
  };

  const startGeneration = async (config: any) => {
    try {
      const payload = {
        vibe: config.vibe,
        directives: config.directives || '',
        music: { 
          mode: config.musicMode, 
          custom_query: config.musicMode === 'custom' ? config.songQuery : null,
          instrumental: config.instrumentalOnly 
        }
      };
      const res = await projectService.startAnalysis(projectId, payload);
      setJob(res);
      return res;
    } catch (err: any) {
      console.error(err);
      alert(`Failed to start job: ${err.message}`);
      throw err;
    }
  };

  const confirmStory = async (storySummary: string, rewriteInstructions?: string) => {
    if (!job?.id) return;
    try {
      const payload = {
        story_summary: storySummary,
        rewrite_instructions: rewriteInstructions,
        asset_order: job.proposed_asset_order,
        asset_phases: job.asset_phases
      };
      const updatedJob = await projectService.confirmStory(job.id, payload);
      setJob(updatedJob);
      return updatedJob;
    } catch (err: any) {
      console.error(err);
      alert(`Failed to confirm story: ${err.message}`);
      throw err;
    }
  };

  const resetJob = () => {
    setJob(null);
  };

  const renameProject = async (newName: string) => {
    if (!projectId) return;
    try {
      const updated = await projectService.updateProject(projectId, newName);
      setProject(updated);
      return updated;
    } catch (err) {
      console.error('Failed to rename project:', err);
      alert('Failed to rename project.');
      throw err;
    }
  };

  return {
    project,
    mediaAssets,
    job,
    setJob,
    jobHistory,
    loading,
    uploading,
    uploadFile,
    deleteAsset,
    startGeneration,
    confirmStory,
    resetJob,
    renameProject,
  };
}
