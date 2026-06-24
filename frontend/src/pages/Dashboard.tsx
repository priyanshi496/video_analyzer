import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { authService } from '../services/auth';
import { Plus, Film, LogOut, Loader2 } from 'lucide-react';

function ProjectCard({ project, onClick }: { project: any, onClick: () => void }) {
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null);
  const [isImage, setIsImage] = useState(false);

  useEffect(() => {
    const fetchMedia = async () => {
      try {
        const res = await api.get(`/projects/${project.id}/media`);
        if (res.data && res.data.length > 0) {
          setThumbnailUrl(res.data[0].presigned_url);
          setIsImage(res.data[0].is_image);
        }
      } catch (err) {
        // ignore
      }
    };
    fetchMedia();
  }, [project.id]);

  return (
    <div 
      onClick={onClick}
      className="glass-card h-64 flex flex-col cursor-pointer hover:-translate-y-1 hover:shadow-[0_20px_40px_rgba(168,85,247,0.2)] transition-all duration-300 group overflow-hidden relative"
    >
      {/* Thumbnail Background */}
      {thumbnailUrl ? (
        <div className="absolute inset-0 z-0 bg-black">
          {isImage ? (
            <img src={thumbnailUrl} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700" />
          ) : (
            <video src={thumbnailUrl + "#t=0.1"} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700" preload="metadata" />
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />
        </div>
      ) : (
        <div className="absolute inset-0 bg-gradient-to-br from-slate-800 to-slate-900 opacity-90 group-hover:opacity-100 transition-opacity" />
      )}

      {/* Content */}
      <div className="relative z-10 flex flex-col h-full p-6">
        <div className="w-12 h-12 rounded-xl bg-white/30 backdrop-blur-md border border-white/30 flex items-center justify-center mb-auto text-white shadow-sm group-hover:bg-primary group-hover:text-white transition-colors">
          <Film className="w-6 h-6" />
        </div>
        <h3 className="font-bold text-xl text-white truncate mb-1">{project.name || 'Untitled Project'}</h3>
        <p className="text-sm text-white/70 font-medium">
          {new Date(project.created_at).toLocaleDateString()}
        </p>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(true);

  useEffect(() => {
    const fetchProjects = async () => {
      try {
        const res = await api.get('/projects/');
        setProjects(res.data);
      } catch (err) {
        console.error('Failed to fetch projects', err);
      } finally {
        setFetching(false);
      }
    };
    fetchProjects();
  }, []);

  const handleCreateProject = async () => {
    try {
      setLoading(true);
      const res = await api.post('/projects/', { name: '' });
      navigate(`/project/${res.data.id}`);
    } catch (err) {
      console.error(err);
      alert('Failed to create project');
      setLoading(false);
    }
  };

  const handleLogout = () => {
    authService.logout();
  };

  return (
    <div className="min-h-screen p-8 max-w-7xl mx-auto">
      <header className="flex justify-between items-center mb-12 bg-white/30 backdrop-blur-md border border-white/50 p-4 rounded-2xl shadow-sm">
        <h1 className="text-3xl font-bold flex items-center gap-3 text-slate-900">
          <div className="p-2 bg-gradient-to-br from-primary to-secondary rounded-xl text-white shadow-md">
            <Film className="w-7 h-7" />
          </div>
          My Projects
        </h1>
        <button onClick={handleLogout} className="btn-secondary flex items-center gap-2 bg-white/50 hover:bg-white/80">
          <LogOut className="w-4 h-4" /> Sign Out
        </button>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-8">
        <button 
          onClick={handleCreateProject}
          disabled={loading}
          className="glass-card h-64 flex flex-col items-center justify-center gap-4 hover:-translate-y-1 hover:shadow-[0_20px_40px_rgba(168,85,247,0.2)] transition-all duration-300 group cursor-pointer border-dashed border-2 border-primary/30"
        >
          {loading ? (
            <Loader2 className="w-12 h-12 text-primary animate-spin" />
          ) : (
            <>
              <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center group-hover:bg-primary group-hover:text-white text-primary transition-all duration-300 shadow-inner">
                <Plus className="w-8 h-8" />
              </div>
              <span className="font-semibold text-xl text-slate-700 group-hover:text-primary transition-colors">Create New Project</span>
            </>
          )}
        </button>

        {fetching ? (
          <div className="glass-card h-64 flex items-center justify-center">
            <Loader2 className="w-10 h-10 text-primary/50 animate-spin" />
          </div>
        ) : projects.length > 0 ? (
          projects.map((project: any) => (
            <ProjectCard 
              key={project.id} 
              project={project} 
              onClick={() => navigate(`/project/${project.id}`)} 
            />
          ))
        ) : (
          <div className="glass-card h-64 flex flex-col items-center justify-center p-6 text-center opacity-70">
            <div className="w-16 h-16 rounded-full bg-slate-200 flex items-center justify-center mb-4 text-slate-400">
              <Film className="w-8 h-8" />
            </div>
            <p className="font-medium text-slate-600">No projects yet</p>
            <p className="text-sm text-slate-400 mt-1">Create one to get started</p>
          </div>
        )}
      </div>
    </div>
  );
}
