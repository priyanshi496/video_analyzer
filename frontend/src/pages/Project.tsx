import { useEffect, useState, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, Upload, FileVideo, FileImage, Loader2, Play, CheckCircle } from 'lucide-react';
import { projectService } from '../services/projects';

export default function Project() {
  const { id } = useParams();
  const [project, setProject] = useState<any>(null);
  const [mediaAssets, setMediaAssets] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Configuration state
  const [vibe, setVibe] = useState('cinematic');
  const [musicMode, setMusicMode] = useState('ai');
  const [customQuery, setCustomQuery] = useState('');
  const [isInstrumental, setIsInstrumental] = useState(true);
  const [directives, setDirectives] = useState('');

  // Job state
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<any>(null);
  const [jobLoading, setJobLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [editedStory, setEditedStory] = useState('');
  const [storyInitialized, setStoryInitialized] = useState(false);

  useEffect(() => {
    if (id) {
      loadProject(id);
    }
  }, [id]);

  // Polling Job Status
  useEffect(() => {
    let interval: any;
    if (jobId && jobStatus?.status !== 'COMPLETED' && jobStatus?.status !== 'FAILED') {
      interval = setInterval(async () => {
        try {
          const status = await projectService.getJobStatus(jobId);
          setJobStatus(status);
        } catch (e) {
          console.error("Failed to poll status", e);
        }
      }, 3000);
    }
    return () => clearInterval(interval);
  }, [jobId, jobStatus]);

  // Initialize editable story text when job hits STORY_PROPOSED
  useEffect(() => {
    if (jobStatus?.status === 'STORY_PROPOSED' && !storyInitialized) {
      setEditedStory(jobStatus.story_summary || '');
      setStoryInitialized(true);
    } else if (jobStatus?.status === 'PENDING' || jobStatus?.status === 'RUNNING') {
      setStoryInitialized(false);
      setEditedStory('');
    }
  }, [jobStatus?.status, jobStatus?.story_summary, storyInitialized]);

  const loadProject = async (projectId: string) => {
    try {
      const p = await projectService.getProject(projectId);
      setProject(p);
      const m = await projectService.listMedia(projectId);
      setMediaAssets(m || []);
      
      // Try to resume the latest job if one exists
      try {
        const latestJob = await projectService.getLatestJob(projectId);
        if (latestJob && latestJob.status !== 'FAILED') {
          setJobId(latestJob.id);
          setJobStatus(latestJob);
        }
      } catch (err: any) {
        // 404 is expected if there are no jobs yet
        if (err.response?.status !== 404) {
          console.error("Failed to load latest job", err);
        }
      }
    } catch (e) {
      console.error("Failed to load project", e);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || !e.target.files.length || !id) return;
    setUploading(true);
    
    try {
      const filesArray = Array.from(e.target.files);
      await projectService.uploadMedia(id, filesArray);
      await loadProject(id);
    } catch (err) {
      console.error(err);
      alert('Failed to upload files.');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleStartJob = async () => {
    if (!id || mediaAssets.length === 0) {
      alert("You need to upload some media first!");
      return;
    }
    
    setJobLoading(true);
    
    try {
      const payload = {
        vibe,
        directives,
        music: { 
          mode: musicMode, 
          custom_query: musicMode === 'custom' ? customQuery : null,
          instrumental: isInstrumental 
        }
      };
      const res = await projectService.startAnalysis(id, payload);
      setJobId(res.id);
      setJobStatus(res);
    } catch (err: any) {
      console.error(err);
      const detail = err.response?.data?.detail;
      const errorMsg = typeof detail === 'string' ? detail : JSON.stringify(detail) || err.message;
      alert(`Failed to start the job: ${errorMsg}`);
    } finally {
      setJobLoading(false);
    }
  };

  const handleConfirmStory = async () => {
    if (!jobId || !jobStatus) return;
    setConfirming(true);
    try {
      const payload = {
        story_summary: editedStory || jobStatus.story_summary,
        asset_order: jobStatus.proposed_asset_order,
        asset_phases: jobStatus.asset_phases
      };
      await projectService.confirmStory(jobId, payload);
    } catch (err: any) {
      console.error(err);
      alert(`Failed to confirm story: ${err.message}`);
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-transparent">
      {/* Main Content Area */}
      <div className="flex-1 p-8 flex flex-col h-screen overflow-hidden max-w-[1600px] mx-auto w-full">
        <header className="flex items-center gap-4 mb-8">
          <Link to="/" className="p-2 rounded-lg hover:bg-white/50 transition-colors shadow-sm bg-white/30 backdrop-blur-md">
            <ArrowLeft className="w-5 h-5 text-slate-700" />
          </Link>
          
          {/* Project Icon (First Media Asset Thumbnail) */}
          {mediaAssets.length > 0 && mediaAssets[0].presigned_url && (
            <div className="w-12 h-12 rounded-xl overflow-hidden shadow-md shrink-0 bg-slate-200 border border-white/50">
              {mediaAssets[0].is_image ? (
                <img src={mediaAssets[0].presigned_url} className="w-full h-full object-cover" />
              ) : (
                <video src={mediaAssets[0].presigned_url + "#t=0.1"} className="w-full h-full object-cover" preload="metadata" />
              )}
            </div>
          )}

          <h1 className="text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-primary to-secondary">
            {project?.name || 'Project Workspace'}
          </h1>
          <div className="ml-auto px-4 py-1.5 rounded-full bg-white/50 shadow-sm text-sm text-slate-700 font-medium backdrop-blur-md border border-white/50">
            ID: {id?.slice(0, 8)}...
          </div>
        </header>

        <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-8 min-h-0 overflow-y-auto pb-8 pr-2">
          
          {/* Column 1 & 2: Media and Player */}
          <div className="lg:col-span-8 space-y-8">
            
            {/* Upload Area */}
            <div className="glass-card p-8 flex flex-col text-center border-t-4 border-t-primary shadow-[0_8px_30px_rgb(0,0,0,0.06)] relative overflow-hidden">
              <div className="absolute top-0 right-0 w-64 h-64 bg-primary/10 rounded-full blur-3xl -mr-20 -mt-20 pointer-events-none" />
              <div className="absolute bottom-0 left-0 w-64 h-64 bg-secondary/10 rounded-full blur-3xl -ml-20 -mb-20 pointer-events-none" />
              
              <h2 className="text-2xl font-bold mb-2 text-slate-900 relative z-10">Media Assets</h2>
              <p className="text-slate-500 mb-8 relative z-10">Drag and drop your raw videos and images here to begin.</p>
              
              <div 
                onClick={() => fileInputRef.current?.click()}
                className="w-full h-40 border-2 border-dashed border-primary/40 rounded-2xl flex flex-col items-center justify-center bg-white/50 hover:bg-primary/5 hover:border-primary transition-all cursor-pointer relative z-10 shadow-inner group"
              >
                {uploading ? (
                  <Loader2 className="w-8 h-8 text-primary animate-spin" />
                ) : (
                  <>
                    <div className="w-16 h-16 bg-white rounded-full shadow-sm flex items-center justify-center mb-3 group-hover:scale-110 transition-transform">
                      <Upload className="w-8 h-8 text-primary" />
                    </div>
                    <span className="text-slate-700 font-semibold text-lg group-hover:text-primary transition-colors">Click to upload files</span>
                    <span className="text-slate-400 text-sm mt-1">Supports MP4, MOV, JPG, PNG</span>
                  </>
                )}
              </div>
              <input 
                type="file" 
                multiple 
                className="hidden" 
                ref={fileInputRef} 
                onChange={handleFileUpload}
                accept="video/*,image/*"
              />

              {/* Media List */}
              {mediaAssets.length > 0 && (
                <div className="w-full mt-8 flex flex-col gap-3">
                  <h3 className="text-left font-semibold text-slate-700 mb-2 px-1 text-sm">Uploaded Files ({mediaAssets.length})</h3>
                  {mediaAssets.map((asset, idx) => (
                    <div key={idx} className="bg-white/90 backdrop-blur-sm rounded-xl p-3 flex items-center gap-4 shadow-sm border border-slate-200 hover:shadow-md hover:border-primary/30 transition-all group">
                      {/* Thumbnail */}
                      <div className="w-16 h-16 rounded-lg overflow-hidden bg-slate-200 shrink-0 shadow-inner">
                        {asset.is_image ? (
                          <img src={asset.presigned_url} className="w-full h-full object-cover" />
                        ) : (
                          <video src={asset.presigned_url + "#t=0.1"} className="w-full h-full object-cover" preload="metadata" />
                        )}
                      </div>
                      
                      {/* File Info */}
                      <div className="flex flex-col text-left truncate flex-1">
                        <div className="flex items-center gap-2 text-slate-800 font-medium truncate mb-1">
                          {asset.is_image ? <FileImage className="w-4 h-4 shrink-0 text-secondary" /> : <FileVideo className="w-4 h-4 shrink-0 text-primary" />}
                          <span className="truncate">{asset.filename}</span>
                        </div>
                        <span className="text-xs text-slate-500">
                          {asset.file_size_bytes ? (asset.file_size_bytes / (1024 * 1024)).toFixed(2) + ' MB' : 'Unknown size'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Final Player (Shows if job is complete) */}
            {jobStatus?.status === 'COMPLETED' && jobStatus?.final_video_url && (
              <div className="glass-card p-6">
                <h2 className="text-xl font-semibold mb-4 text-slate-900 flex items-center gap-2">
                  <CheckCircle className="text-success w-6 h-6" /> 
                  Final Reel
                </h2>
                <div className="bg-black rounded-lg overflow-hidden aspect-video shadow-lg">
                  <video src={jobStatus.final_video_url} controls className="w-full h-full object-contain" />
                </div>
              </div>
            )}
          </div>

          {/* Column 3: Config and Job Status */}
          <div className="lg:col-span-4 flex flex-col gap-6 sticky top-0 h-fit pb-8">
            <div className="glass-card p-6 flex flex-col relative overflow-hidden border-t-4 border-t-secondary shadow-[0_8px_30px_rgb(0,0,0,0.06)]">
              <div className="absolute top-0 right-0 w-full h-full bg-gradient-to-br from-secondary/5 to-transparent pointer-events-none" />
              <h2 className="text-2xl font-bold mb-6 text-slate-900 relative z-10 flex items-center gap-2">
                Configuration
              </h2>
            
            <div className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-2">Vibe</label>
                <select 
                  className="input-field"
                  value={vibe}
                  onChange={(e) => setVibe(e.target.value)}
                >
                  <option value="cinematic">Cinematic</option>
                  <option value="energetic">Energetic</option>
                  <option value="romantic">Romantic</option>
                  <option value="spiritual">Spiritual</option>
                  <option value="garba">Garba</option>
                </select>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-slate-600 mb-2">Music Mode</label>
                <select 
                  className="input-field"
                  value={musicMode}
                  onChange={(e) => setMusicMode(e.target.value)}
                >
                  <option value="ai">AI Catalog Match (Fast)</option>
                  <option value="suno">Suno AI Generation</option>
                  <option value="custom">Custom Search</option>
                  <option value="none">None</option>
                </select>
              </div>

              {musicMode === 'custom' && (
                <div>
                  <label className="block text-sm font-medium text-slate-600 mb-2">Custom Song Query</label>
                  <input 
                    type="text" 
                    className="input-field" 
                    placeholder="e.g. Satranga Arijit Singh"
                    value={customQuery}
                    onChange={(e) => setCustomQuery(e.target.value)}
                  />
                </div>
              )}

              {musicMode !== 'none' && (
                <div className="flex items-center gap-2">
                  <input 
                    type="checkbox" 
                    id="instrumental-check" 
                    checked={isInstrumental}
                    onChange={(e) => setIsInstrumental(e.target.checked)}
                    className="w-4 h-4 text-primary rounded border-slate-300 focus:ring-primary"
                  />
                  <label htmlFor="instrumental-check" className="text-sm font-medium text-slate-600">
                    Instrumental Only
                  </label>
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-slate-600 mb-2">Directives (Optional)</label>
                <textarea 
                  className="input-field h-24 resize-none" 
                  placeholder="e.g., Make it fast paced..."
                  value={directives}
                  onChange={(e) => setDirectives(e.target.value)}
                />
              </div>
            </div>
            </div>

            {jobStatus ? (
              <div className="glass-card p-6 border border-primary/20 bg-white/80 shadow-lg relative overflow-hidden rounded-3xl">
                <div className="absolute top-0 right-0 w-32 h-32 bg-primary/10 rounded-full blur-2xl -mr-10 -mt-10 pointer-events-none" />
                <h3 className="font-bold text-lg text-slate-800 mb-3 flex items-center gap-2 relative z-10">
                  {jobStatus.status === 'COMPLETED' ? <CheckCircle className="text-success w-6 h-6"/> : <Loader2 className="w-6 h-6 animate-spin text-primary"/>}
                  Status: <span className="text-primary">{jobStatus.status}</span>
                </h3>
                <div className="w-full bg-slate-100 rounded-full h-3 mt-4 overflow-hidden relative z-10 shadow-inner">
                  <div className="bg-gradient-to-r from-primary to-secondary h-full rounded-full transition-all duration-500 relative" style={{ width: `${jobStatus.progress}%` }}>
                    <div className="absolute inset-0 bg-white/20 w-full h-full animate-[shimmer_2s_infinite]"></div>
                  </div>
                </div>
                {jobStatus.error_message && (
                  <p className="text-error text-sm mt-2">{jobStatus.error_message}</p>
                )}
              </div>
            ) : (
              <button 
                onClick={handleStartJob}
                disabled={jobLoading || mediaAssets.length === 0}
                className="btn-primary w-full py-4 text-lg font-bold flex items-center justify-center gap-3 bg-gradient-to-r from-primary to-secondary hover:from-primary-hover hover:to-secondary shadow-lg hover:shadow-xl hover:-translate-y-0.5 transition-all disabled:opacity-50 disabled:hover:translate-y-0"
              >
                {jobLoading ? <Loader2 className="w-6 h-6 animate-spin" /> : <Play className="w-6 h-6 fill-current" />}
                Generate Reel
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Story Review Modal */}
      {jobStatus?.status === 'STORY_PROPOSED' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-8 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="glass-card max-w-5xl w-full h-[80vh] flex flex-col p-10 bg-white/95 shadow-2xl relative overflow-hidden animate-in zoom-in-95 duration-300">
            <div className="absolute top-0 left-0 w-full h-2 bg-gradient-to-r from-primary to-secondary" />
            <h2 className="text-4xl font-bold text-slate-900 mb-4">Review AI Story</h2>
            <p className="text-slate-600 mb-8 text-lg">
              The AI has proposed the following narrative. Feel free to edit the description before confirming. This description directly guides the final reel generation.
            </p>
            <div className="flex-1 min-h-0 flex flex-col relative">
              <textarea 
                className="w-full h-full text-xl text-slate-800 bg-slate-50/80 p-8 rounded-3xl border-2 border-primary/20 resize-none focus:outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 shadow-inner"
                value={editedStory}
                onChange={(e) => setEditedStory(e.target.value)}
              />
            </div>
            <div className="mt-8 flex justify-end">
              <button 
                onClick={handleConfirmStory}
                disabled={confirming}
                className="btn-primary px-12 py-5 text-xl font-bold flex items-center gap-3 bg-gradient-to-r from-primary to-secondary hover:shadow-xl hover:-translate-y-1 transition-all rounded-2xl disabled:opacity-50"
              >
                {confirming ? <Loader2 className="w-7 h-7 animate-spin" /> : <CheckCircle className="w-7 h-7" />}
                Approve & Generate Reel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
