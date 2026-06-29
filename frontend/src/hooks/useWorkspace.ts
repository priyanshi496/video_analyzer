import { useState, useEffect, useCallback, useRef } from 'react';
import { projectService } from '../services/projects';

// How long (ms) a job can sit in RUNNING with no progress change before
// we consider the worker dead. 15 minutes is generous for a long analysis.
const STALE_JOB_TIMEOUT_MS = 15 * 60 * 1000;

export function useWorkspace(projectId: string) {
  const [project, setProject] = useState<any>(null);
  const [mediaAssets, setMediaAssets] = useState<any[]>([]);
  const [job, setJob] = useState<any>(null);
  const [jobHistory, setJobHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);

  // Stale watchdog: track when we last saw a progress change
  const lastProgressRef = useRef<number | null>(null);
  const lastProgressTimeRef = useRef<number | null>(null);

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

  // Polling Job Status + Stale Worker Watchdog
  useEffect(() => {
    let interval: any;
    if (job?.id && job.status !== 'COMPLETED' && job.status !== 'FAILED') {
      // Initialize stale tracker when we start polling a new job
      if (lastProgressRef.current !== job.progress) {
        lastProgressRef.current = job.progress;
        lastProgressTimeRef.current = Date.now();
      }

      interval = setInterval(async () => {
        try {
          const status = await projectService.getJobStatus(job.id);

          // ── Stale worker watchdog ──────────────────────────────────
          // If the job is RUNNING, check if progress has been stuck too long
          if (status.status === 'RUNNING') {
            if (status.progress !== lastProgressRef.current) {
              // Progress changed — worker is alive, reset the clock
              lastProgressRef.current = status.progress;
              lastProgressTimeRef.current = Date.now();
            } else if (
              lastProgressTimeRef.current &&
              Date.now() - lastProgressTimeRef.current > STALE_JOB_TIMEOUT_MS
            ) {
              // Progress has been frozen for too long — worker is dead
              console.warn('[useWorkspace] Stale job detected — marking as failed locally.');
              setJob({
                ...status,
                status: 'FAILED',
                error_message: 'Job failed due to worker timeout. The background worker may have crashed. Please try again.',
              });
              return;
            }
          }
          // ──────────────────────────────────────────────────────────

          setJob(status);
        } catch (e) {
          console.error('Failed to poll status', e);
        }
      }, 3000);
    }
    return () => clearInterval(interval);
  }, [job?.id, job?.status]);

  const uploadFile = async (file: File) => {
    setUploading(true);
    setWorkspaceError(null);
    try {
      await projectService.uploadMedia(projectId, [file]);
      const m = await projectService.listMedia(projectId);
      setMediaAssets(m || []);
    } catch (err: any) {
      console.error(err);
      setWorkspaceError(err.userMessage || 'Failed to upload file. Please try again.');
    } finally {
      setUploading(false);
    }
  };

  const deleteAsset = async (assetId: string) => {
    setWorkspaceError(null);
    try {
      await projectService.deleteMedia(projectId, assetId);
      setMediaAssets(prev => prev.filter(a => a.id !== assetId));
    } catch (err: any) {
      console.error(err);
      setWorkspaceError(err.userMessage || 'Failed to delete media. Please try again.');
    }
  };

  const startGeneration = async (config: any) => {
    setWorkspaceError(null);
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
      setWorkspaceError(err.userMessage || 'Failed to start generation. Please try again.');
      throw err;
    }
  };

  const confirmStory = async (storySummary: string, rewriteInstructions?: string, regenerate: boolean = false) => {
    if (!job?.id) return;
    setWorkspaceError(null);
    try {
      const payload = {
        story_summary: storySummary,
        rewrite_instructions: rewriteInstructions,
        regenerate: regenerate,
        asset_order: job.proposed_asset_order,
        asset_phases: job.asset_phases
      };
      const updatedJob = await projectService.confirmStory(job.id, payload);
      setJob(updatedJob);
      return updatedJob;
    } catch (err: any) {
      console.error(err);
      setWorkspaceError(err.userMessage || 'Something went wrong. Please try again.');
      throw err;
    }
  };

  const regenerateStory = async () => {
    if (!job?.id) return;
    setWorkspaceError(null);
    try {
      const updatedJob = await projectService.regenerateStory(job.id);
      setJob(updatedJob);
      return updatedJob;
    } catch (err: any) {
      console.error(err);
      setWorkspaceError(err.userMessage || 'Failed to regenerate story. Please try again.');
      throw err;
    }
  };

  const resetJob = () => {
    setJob(null);
    setWorkspaceError(null);
    lastProgressRef.current = null;
    lastProgressTimeRef.current = null;
  };

  const renameProject = async (newName: string) => {
    if (!projectId) return;
    try {
      const updated = await projectService.updateProject(projectId, newName);
      setProject(updated);
      return updated;
    } catch (err: any) {
      console.error('Failed to rename project:', err);
      setWorkspaceError(err.userMessage || 'Failed to rename project. Please try again.');
      throw err;
    }
  };

  return {
    project,
    mediaAssets,
    job,
    jobHistory,
    loading,
    uploading,
    workspaceError,
    uploadFile,
    deleteAsset,
    startGeneration,
    confirmStory,
    regenerateStory,
    resetJob,
    renameProject,
  };
}
