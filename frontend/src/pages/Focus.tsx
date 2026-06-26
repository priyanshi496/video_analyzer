import { useState, useEffect } from 'react';
import { Aperture, Loader2, ArrowRight } from 'lucide-react';
import { projectService } from '../services/projects';
import { useNavigate } from 'react-router-dom';
import type { Project } from '../types';

export default function FocusScreen() {
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
