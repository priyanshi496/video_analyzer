import { useState, useEffect, useRef } from 'react';
import { Play, Heart, Loader2, FolderOpen, ArrowRight } from 'lucide-react';
import { projectService } from '../services/projects';
import { useNavigate } from 'react-router-dom';
import type { Project, Job } from '../types';

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

export default function Feed() {
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
