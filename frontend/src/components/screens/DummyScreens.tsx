import { useState, useEffect, useRef } from 'react';
import { 
  Play, LayoutGrid, Aperture, BarChart2, Heart, MessageCircle, Share2, 
  Search, Grid, List, Sparkles, TrendingUp, Clock, HardDrive, Cpu, 
  ShieldCheck, Loader2, FolderOpen, ArrowRight
} from 'lucide-react';
import { projectService } from '../../services/projects';
import { useNavigate } from 'react-router-dom';
import type { Project, MediaAsset, Job } from '../../types';

// Helper ReelItem component to handle playing/pausing of individual video feeds
function ReelItem({ 
  project, 
  job, 
  isActive, 
  liked, 
  onLikeToggle, 
  onOpen,
  index,
  total
}: { 
  project: Project; 
  job: Job; 
  isActive: boolean; 
  liked: boolean; 
  onLikeToggle: () => void; 
  onOpen: () => void;
  index: number;
  total: number;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoRef.current) {
      if (isActive) {
        videoRef.current.play().catch(err => console.debug("Video autoplay was prevented", err));
      } else {
        videoRef.current.pause();
        videoRef.current.currentTime = 0;
      }
    }
  }, [isActive]);

  return (
    <div className="w-full h-full flex-shrink-0 snap-start relative flex flex-col justify-between select-none overflow-hidden bg-black">
      {/* Real Video Player */}
      <div className="absolute inset-0 bg-black z-0 flex items-center justify-center">
        {job.final_video_url && (
          <video 
            ref={videoRef}
            src={job.final_video_url} 
            className="w-full h-full object-contain" 
            loop 
            muted 
            playsInline
          />
        )}
      </div>

      {/* Top Header Overlay */}
      <div className="relative z-10 p-4 flex justify-between items-center bg-gradient-to-b from-black/80 to-transparent">
        <span className="text-white font-bold tracking-tight text-sm drop-shadow-md">ReelFeed AI</span>
        <span className="text-[10px] text-white bg-white/20 backdrop-blur-md px-2 py-0.5 rounded-full font-semibold">
          {index + 1} / {total}
        </span>
      </div>

      {/* Right Action buttons */}
      <div className="absolute right-4 bottom-24 z-10 flex flex-col gap-4 items-center">
        <button onClick={onLikeToggle} className="flex flex-col items-center gap-1">
          <div className={`w-10 h-10 rounded-full flex items-center justify-center backdrop-blur-md transition-all ${liked ? 'bg-orange-600 text-white shadow-md shadow-orange-600/30' : 'bg-black/40 text-white'}`}>
            <Heart className={`w-5 h-5 ${liked ? 'fill-current' : ''}`} />
          </div>
          <span className="text-[10px] text-white font-semibold drop-shadow-sm">{liked ? 1 : 0}</span>
        </button>

        <button 
          onClick={onOpen}
          className="flex flex-col items-center gap-1"
        >
          <div className="w-10 h-10 rounded-full bg-black/40 text-white hover:bg-black/60 flex items-center justify-center backdrop-blur-md transition-all">
            <FolderOpen className="w-5 h-5" />
          </div>
          <span className="text-[10px] text-white font-semibold drop-shadow-sm">Open</span>
        </button>
      </div>

      {/* Info Overlay */}
      <div className="relative z-10 p-4 bg-gradient-to-t from-black/90 via-black/50 to-transparent pt-20 text-left max-w-full">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-orange-600 flex items-center justify-center text-white font-bold text-xs uppercase shadow-sm">
            {project.name.charAt(0)}
          </div>
          <div>
            <p className="text-xs font-bold text-white drop-shadow-sm">{project.name}</p>
            <p className="text-[9px] text-white/70 capitalize drop-shadow-sm">{job.vibe || 'cinematic'} preset</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ==========================================
// 1. MOBILE FEED SCREEN (Real completed reels)
// ==========================================
export function FeedScreen() {
  const navigate = useNavigate();
  const [reels, setReels] = useState<{ project: Project; job: Job }[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [likedMap, setLikedMap] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const fetchAllReels = async () => {
      try {
        const projectsData: Project[] = await projectService.getProjects();
        const reelsList: { project: Project; job: Job }[] = [];
        
        for (const p of projectsData) {
          const jobs: Job[] = await projectService.listJobs(p.id);
          const completedJobs = jobs.filter(j => j.status === 'COMPLETED' && j.final_video_url);
          completedJobs.forEach(job => {
            reelsList.push({ project: p, job });
          });
        }
        setReels(reelsList);
      } catch (err) {
        console.error('Failed to load reels feed:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchAllReels();
  }, []);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const container = e.currentTarget;
    const height = container.clientHeight;
    if (height > 0) {
      const idx = Math.round(container.scrollTop / height);
      if (idx !== currentIdx && idx >= 0 && idx < reels.length) {
        setCurrentIdx(idx);
      }
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-slate-50 p-8">
        <Loader2 className="w-8 h-8 text-orange-500 animate-spin" />
        <span className="text-sm text-slate-500 mt-2">Loading highlight feed...</span>
      </div>
    );
  }

  if (reels.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center bg-slate-50">
        <div className="w-16 h-16 rounded-full bg-orange-50 border border-orange-100 flex items-center justify-center mb-4">
          <Play className="w-6 h-6 text-orange-500 ml-0.5" />
        </div>
        <h2 className="text-lg font-bold text-slate-800">No Reels Yet</h2>
        <p className="text-sm text-slate-500 mt-1 max-w-xs mx-auto mb-6">
          Create a project, upload clips, and generate an AI montage to watch your feed.
        </p>
        <button 
          onClick={() => navigate('/')}
          className="flex items-center gap-2 bg-orange-600 hover:bg-orange-500 text-white font-semibold py-2.5 px-6 rounded-full text-sm shadow-sm transition-all"
        >
          Go to Dashboard
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    );
  }

  return (
    <div 
      onScroll={handleScroll}
      className="flex-1 h-full bg-black overflow-y-auto snap-y snap-mandatory scrollbar-hide"
      style={{ height: 'calc(100vh - 4rem)' }}
    >
      {reels.map((reel, idx) => (
        <ReelItem
          key={reel.job.id}
          project={reel.project}
          job={reel.job}
          isActive={idx === currentIdx}
          liked={!!likedMap[reel.job.id]}
          onLikeToggle={() => setLikedMap(prev => ({ ...prev, [reel.job.id]: !prev[reel.job.id] }))}
          onOpen={() => navigate(`/project/${reel.project.id}`)}
          index={idx}
          total={reels.length}
        />
      ))}
    </div>
  );
}

// ==========================================
// 2. GRID / MEDIA LIBRARY (Real assets)
// ==========================================
export function GridScreen() {
  const [media, setMedia] = useState<MediaAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'video' | 'image'>('all');

  useEffect(() => {
    const fetchAllMedia = async () => {
      try {
        const projectsData: Project[] = await projectService.getProjects();
        let allMedia: MediaAsset[] = [];
        for (const p of projectsData) {
          const projectMedia = await projectService.listMedia(p.id);
          allMedia = allMedia.concat(projectMedia);
        }
        setMedia(allMedia);
      } catch (err) {
        console.error('Failed to load media grid:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchAllMedia();
  }, []);

  const filteredMedia = media.filter(m => {
    if (filter === 'video') return !m.is_image;
    if (filter === 'image') return m.is_image;
    return true;
  });

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-slate-50 p-8">
        <Loader2 className="w-8 h-8 text-orange-500 animate-spin" />
        <span className="text-sm text-slate-500 mt-2">Loading library...</span>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-slate-50 p-4 overflow-y-auto pb-20 sm:pb-8 text-left">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-slate-800">Media Library</h2>
        <span className="text-xs text-slate-500 font-semibold bg-slate-100 py-1 px-3 rounded-full">
          {media.length} items
        </span>
      </div>

      {/* Filter Tabs */}
      <div className="flex gap-2 mb-4">
        {['all', 'video', 'image'].map(type => (
          <button 
            key={type}
            onClick={() => setFilter(type as any)}
            className={`px-4 py-1.5 rounded-full text-xs font-semibold border transition-all ${filter === type ? 'bg-orange-600 text-white border-orange-600' : 'bg-white text-slate-600 border-slate-200'}`}
          >
            <span className="capitalize">{type}s</span>
          </button>
        ))}
      </div>

      {filteredMedia.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-3xl border border-slate-100 shadow-sm">
          <FolderOpen className="w-8 h-8 text-slate-300 mx-auto mb-2" />
          <p className="text-sm text-slate-500">No media assets found matching filter.</p>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-2">
          {filteredMedia.map(item => (
            <div key={item.id} className="aspect-square rounded-2xl overflow-hidden relative border border-slate-100 bg-slate-200">
              {item.presigned_url && (
                item.is_image ? (
                  <img src={item.presigned_url} className="w-full h-full object-cover" loading="lazy" />
                ) : (
                  <video src={item.presigned_url + '#t=0.1'} className="w-full h-full object-cover" preload="metadata" />
                )
              )}
              {!item.is_image && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/10">
                  <Play className="w-4 h-4 text-white fill-white opacity-80" />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ==========================================
// 3. FOCUS / AI DIRECTOR SCREEN (Real settings selector)
// ==========================================
export function FocusScreen() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    projectService.getProjects()
      .then(data => {
        setProjects(data);
        if (data.length > 0) setSelectedProjectId(data[0].id);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const handleEditConfig = () => {
    if (selectedProjectId) {
      navigate(`/project/${selectedProjectId}`);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-slate-50 p-8">
        <Loader2 className="w-8 h-8 text-orange-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-slate-50 p-4 overflow-y-auto pb-20 sm:pb-8 text-left">
      <h2 className="text-xl font-bold text-slate-800 mb-1">AI Director</h2>
      <p className="text-xs text-slate-500 mb-6">Select a project to configure prompts and generation parameters.</p>

      {projects.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-3xl border border-slate-100 shadow-sm">
          <Aperture className="w-8 h-8 text-slate-300 mx-auto mb-2" />
          <p className="text-sm text-slate-500 mb-4">You need to create a project first.</p>
          <button onClick={() => navigate('/')} className="bg-orange-600 text-white text-xs font-semibold py-2 px-4 rounded-full">
            Create Project
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="bg-white border border-slate-100 rounded-3xl p-5 shadow-sm space-y-4">
            <label className="block text-xs font-bold text-slate-500 uppercase">Select Target Project</label>
            <select 
              value={selectedProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
              className="w-full p-3 rounded-2xl bg-slate-50 border border-slate-200 text-sm focus:outline-none"
            >
              {projects.map(p => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>

            <button 
              onClick={handleEditConfig}
              className="w-full flex items-center justify-center gap-2 bg-orange-600 hover:bg-orange-500 text-white font-semibold py-3 rounded-2xl text-sm shadow-sm transition-all"
            >
              Open Project Studio
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ==========================================
// 4. ANALYTICS SCREEN (Real totals)
// ==========================================
export function AnalyticsScreen() {
  const [projectsCount, setProjectsCount] = useState(0);
  const [mediaCount, setMediaCount] = useState(0);
  const [reelsCount, setReelsCount] = useState(0);
  const [totalSizeMB, setTotalSizeMB] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const projectsData: Project[] = await projectService.getProjects();
        setProjectsCount(projectsData.length);
        
        let mCount = 0;
        let rCount = 0;
        let bytesSum = 0;

        for (const p of projectsData) {
          const media = await projectService.listMedia(p.id);
          mCount += media.length;
          media.forEach(m => {
            bytesSum += m.file_size_bytes || 0;
          });

          const jobs = await projectService.listJobs(p.id);
          rCount += jobs.filter(j => j.status === 'COMPLETED').length;
        }

        setMediaCount(mCount);
        setReelsCount(rCount);
        setTotalSizeMB(Math.round(bytesSum / 1_000_000));
      } catch (err) {
        console.error('Failed to load stats:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
  }, []);

  const stats = [
    { label: 'Total Projects', value: String(projectsCount), icon: Sparkles, color: 'text-orange-500 bg-orange-50 border-orange-100' },
    { label: 'Reels Created', value: String(reelsCount), icon: TrendingUp, color: 'text-amber-500 bg-amber-50 border-amber-100' },
    { label: 'Media Files', value: String(mediaCount), icon: Clock, color: 'text-blue-500 bg-blue-50 border-blue-100' },
    { label: 'Total Storage', value: `${totalSizeMB} MB`, icon: HardDrive, color: 'text-green-500 bg-green-50 border-green-100' }
  ];

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-slate-50 p-8">
        <Loader2 className="w-8 h-8 text-orange-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-slate-50 p-4 overflow-y-auto pb-20 sm:pb-8 text-left">
      <h2 className="text-xl font-bold text-slate-800 mb-1">Pipeline Performance</h2>
      <p className="text-xs text-slate-500 mb-6">Track your AI rendering and storage status.</p>

      {/* Grid of stats */}
      <div className="grid grid-cols-2 gap-3 mb-6">
        {stats.map(stat => (
          <div key={stat.label} className="bg-white border border-slate-100 p-4 rounded-3xl shadow-sm flex flex-col justify-between gap-4">
            <div className={`w-8 h-8 rounded-xl flex items-center justify-center border ${stat.color}`}>
              <stat.icon className="w-4 h-4" />
            </div>
            <div>
              <span className="text-2xl font-bold text-slate-800 block leading-none mb-1">{stat.value}</span>
              <span className="text-[10px] text-slate-400 font-medium block">{stat.label}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Health indicator */}
      <div className="bg-white border border-slate-100 p-4 rounded-3xl flex items-center gap-3.5 shadow-sm">
        <div className="w-10 h-10 rounded-full bg-green-50 border border-green-100 flex items-center justify-center flex-shrink-0">
          <ShieldCheck className="w-5 h-5 text-green-600" />
        </div>
        <div>
          <span className="text-xs font-semibold text-slate-800 block">Systems Operational</span>
          <span className="text-[10px] text-slate-400 block mt-0.5">MinIO, Redis, and Database connections healthy</span>
        </div>
      </div>
    </div>
  );
}
