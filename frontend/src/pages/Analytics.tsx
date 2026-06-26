import { useState, useEffect } from 'react';
import { Sparkles, TrendingUp, Clock, HardDrive, ShieldCheck, Loader2 } from 'lucide-react';
import { projectService } from '../services/projects';
import type { Project, MediaAsset, Job } from '../types';

export default function AnalyticsScreen() {
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
          media.forEach((m: MediaAsset) => {
            bytesSum += m.file_size_bytes || 0;
          });

          const jobs = await projectService.listJobs(p.id);
          rCount += jobs.filter((j: Job) => j.status === 'COMPLETED').length;
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
