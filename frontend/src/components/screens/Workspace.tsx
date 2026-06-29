import { useState, useCallback, useRef, useEffect } from 'react';
import {
  ArrowLeft,
  Plus,
  Send,
  Trash2,
  Check,
  Pencil,
  MoreHorizontal,
  Download,
  RotateCcw,
  Volume2,
  Film,
  X,
  Maximize2,
  RefreshCw,
} from 'lucide-react';
import { useWorkspace } from '../../hooks/useWorkspace';
import { vibeOptions, musicModeOptions } from '../../lib/utils';
import type { GenerationConfig, MediaAsset } from '../../types';

import { useParams, useNavigate } from 'react-router-dom';

// Chat flow phases
type ChatPhase =
  | 'upload'       // no media yet
  | 'vibe'         // asking vibe preference
  | 'music'        // asking music mode
  | 'song_query'   // custom song text input
  | 'processing'   // PENDING / RUNNING
  | 'story'        // STORY_PROPOSED
  | 'rendering'    // confirmed story, rendering
  | 'complete'     // COMPLETED
  | 'failed';      // FAILED

interface ConfigState {
  vibe: GenerationConfig['vibe'];
  musicMode: GenerationConfig['musicMode'];
  instrumentalOnly: boolean;
  directives: string;
  songQuery: string;
}

const analysisMessages = [
  'Looking at your pics...',
  'Wow, so beautiful!',
  'Analyzing quality...',
  'Oh, this one is a lil shaky...',
  'Finding the perfect highlights...',
  'Scanning for the best frames...',
  'This is going to look amazing...',
  'Going through your clips...',
  'Taking it all in...',
  'Okay, what do we have here...',
  'Checking the quality...',
  'Is this one sharp enough...',
  'A little blurry, but salvageable...',
  'This one is steady, nice...',
  'Hmm, bit shaky on this clip...',
  'Stabilizing in my head...',
  'Rating each shot...',
  'Sorting the good from the meh...',
  'Hmm, interesting...',
  'Flipping through everything...',
  'Reading the room...',
  'Getting the full picture...',
  'Noting the details...',
 'Flagging the wobbly ones...',
  'Checking for motion blur...',
  'Some of these are really sharp...',
  'Filtering out the rough ones...',
  'Keeping only the good stuff...',
  'Quality check, almost done...',
  'Getting a feel for the vibe...',
  'Understanding the story...',
  'Almost have a sense of it...',
  'Just need a moment more...',
];

const renderMessages = [
  'Analyzing your best moments.',
  'Finding the perfect sequence.',
  'Generating script.',
  'Cooking up your next viral cut.',
  'Syncing vibe, voice, and visuals.',
  'Stitching the story together.',
  'Matching beats to your clips.',
  'Laying down the timeline...',
  'Cutting to the good parts...',
  'Sequencing the shots...',
  'Locking in the transitions...',
  'Rendering frame by frame...',
  'Building the final cut...',
  'Mixing the audio...',
  'Syncing the music drop...',
  'Polishing every second...',
  'Adding the finishing layers...',
  'Encoding the magic...',
  'Almost out of the oven...',
  'Final render in progress...',
  'Exporting your masterpiece...',
  'Putting the bow on it...',
  'This one slaps, trust.',
  'Done is near.',
];

const triggerDownload = async (url: string, filename: string = 'reel.mp4') => {
  try {
    const response = await fetch(url);
    const blob = await response.blob();
    const blobUrl = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(blobUrl);
  } catch (err) {
    console.error('Download failed:', err);
    window.open(url, '_blank');
  }
};

export function Workspace() {
  const { id: projectId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const onBack = () => navigate('/');

  const {
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
  } = useWorkspace(projectId || '');

  const pastJobs = jobHistory?.filter((h: any) => h.id !== job?.id && h.status === 'COMPLETED') || [];

  const [chatPhase, setChatPhase] = useState<ChatPhase>('upload');
  const [showPastReels, setShowPastReels] = useState(false);
  const [isEditingName, setIsEditingName] = useState(false);
  const [tempName, setTempName] = useState('');
  const [config, setConfig] = useState<ConfigState>({
    vibe: 'cinematic',
    musicMode: 'ai-catalog',
    instrumentalOnly: false,
    directives: '',
    songQuery: '',
  });
  const [rewriteInstruction, setRewriteInstruction] = useState('');
  const [editingStory, setEditingStory] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [inputText, setInputText] = useState('');
  const [activePreviewUrl, setActivePreviewUrl] = useState<string | null>(null);

  const handleStartRename = () => {
    setTempName(project?.name || '');
    setIsEditingName(true);
  };

  const handleSaveRename = async () => {
    const trimmed = tempName.trim();
    if (trimmed && trimmed !== project?.name) {
      try {
        await renameProject(trimmed);
      } catch (e) {
        // ignore/revert
      }
    }
    setIsEditingName(false);
  };

  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const storyTextareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatPhase, job?.status]);

  // Lock body scroll when any modal is open
  useEffect(() => {
    const isModalOpen = showPastReels || !!activePreviewUrl;
    if (isModalOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [showPastReels, activePreviewUrl]);

  // Advance phase after first upload
  useEffect(() => {
    if (mediaAssets.length > 0 && chatPhase === 'upload') {
      setChatPhase('vibe');
    }
  }, [mediaAssets.length, chatPhase]);

  // Sync job status to chat phase
  useEffect(() => {
    if (!job) return;

    if (job.status === 'PENDING' || job.status === 'RUNNING') {
      if (job.story_summary) {
        setChatPhase('rendering');
      } else {
        setChatPhase('processing');
      }
    } else if (job.status === 'STORY_PROPOSED') {
      setChatPhase('story');
    } else if (job.status === 'COMPLETED') {
      setChatPhase('complete');
    } else if (job.status === 'FAILED') {
      setChatPhase('failed');
    }
  }, [job?.status, job?.story_summary]);

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    for (const file of files) {
      if (file.type.startsWith('video/') || file.type.startsWith('image/')) {
        await uploadFile(file);
      }
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [uploadFile]);

  const handleVibeSelect = (vibe: ConfigState['vibe']) => {
    setConfig(prev => ({ ...prev, vibe }));
    setTimeout(() => setChatPhase('music'), 400);
  };

  const handleMusicSelect = (musicMode: ConfigState['musicMode']) => {
    setConfig(prev => {
      const updated = { ...prev, musicMode };
      if (musicMode !== 'custom') {
        // Start generation directly!
        startGeneration(updated);
        setTimeout(() => setChatPhase('processing'), 400);
      } else {
        // Go to custom song query text input phase
        setTimeout(() => setChatPhase('song_query'), 400);
      }
      return updated;
    });
  };

  const handleSendSongQuery = () => {
    const query = inputText.trim();
    if (!query) return;
    setInputText('');
    
    setConfig(prev => {
      const updated = { ...prev, songQuery: query };
      startGeneration(updated);
      return updated;
    });
    setChatPhase('processing');
  };

  const handleConfirmStory = async () => {
    setConfirming(true);
    setChatPhase('rendering');
    try {
      if (editingStory && rewriteInstruction.trim()) {
        // User typed instructions in the box
        await confirmStory(job?.story_summary || '', rewriteInstruction.trim());
      } else {
        // User did not edit the box
        await confirmStory(job?.story_summary || '', '');
      }
    } catch (err) {
      // Revert back if it failed so user isn't stuck
      setChatPhase('story');
    } finally {
      setConfirming(false);
    }
  };

  const handleRegenerateStory = async () => {
    setIsRegenerating(true);
    try {
      await regenerateStory();
    } catch (err) {
      console.error(err);
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleResetAll = () => {
    resetJob();
    setChatPhase(mediaAssets.length > 0 ? 'vibe' : 'upload');
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-[#F2F1EC]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-surface-300 border-t-orange-500 rounded-full animate-spin" />
          <p className="text-surface-500 text-sm">Loading project...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-[#F2F1EC] relative overflow-hidden min-h-0">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="video/*,image/*"
        className="hidden"
        onChange={handleFileSelect}
      />

      {/* Error Toast */}
      {workspaceError && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2.5 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-2.5 shadow-md animate-slide-up">
          <span className="flex-1">{workspaceError}</span>
        </div>
      )}

      {/* Top bar */}
      <div className="flex items-center justify-between px-5 py-3.5 bg-transparent">
        <button
          onClick={onBack}
          className="w-9 h-9 rounded-full bg-surface-200/80 flex items-center justify-center hover:bg-surface-300/80 transition-colors"
        >
          <ArrowLeft className="w-4 h-4 text-surface-700" />
        </button>
        {isEditingName ? (
          <div className="flex-1 max-w-[220px] mx-2 flex items-center gap-1.5 bg-white border border-orange-300 rounded-full px-3 py-1 shadow-sm animate-scale-in">
            <input
              type="text"
              value={tempName}
              onChange={(e) => setTempName(e.target.value)}
              onBlur={handleSaveRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSaveRename();
                if (e.key === 'Escape') setIsEditingName(false);
              }}
              autoFocus
              className="w-full bg-transparent text-sm font-semibold text-slate-850 focus:outline-none text-center"
              maxLength={50}
            />
            <button
              onClick={handleSaveRename}
              className="p-0.5 text-orange-500 hover:text-orange-600 hover:bg-orange-50 rounded-full transition-colors cursor-pointer"
            >
              <Check className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          <button
            onClick={handleStartRename}
            className="flex items-center gap-1.5 text-sm font-semibold text-surface-700 hover:text-orange-500 hover:bg-white/65 hover:shadow-sm px-3.5 py-1.5 rounded-full transition-all max-w-[220px] min-w-0 truncate group cursor-pointer"
            title="Rename Project"
          >
            <span className="truncate">{project?.name || 'Project'}</span>
            <Pencil className="w-3 h-3 text-surface-450 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
          </button>
        )}
        <button
          onClick={() => setShowPastReels(true)}
          className="w-9 h-9 rounded-full bg-surface-200/80 flex items-center justify-center hover:bg-surface-300/80 transition-colors"
        >
          <MoreHorizontal className="w-4 h-4 text-surface-700" />
        </button>
      </div>

      {/* Past Reels Modal */}
      {showPastReels && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm max-h-[80vh] flex flex-col overflow-hidden animate-slide-up">
            <div className="px-5 py-4 border-b border-surface-200 flex items-center justify-between bg-surface-50">
              <h3 className="text-lg font-semibold text-surface-900 flex items-center gap-2">
                <Film className="w-5 h-5 text-orange-500" />
                Past Reels
              </h3>
              <button onClick={() => setShowPastReels(false)} className="p-2 text-surface-400 hover:text-surface-700 hover:bg-surface-200 rounded-full transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-5 overflow-y-auto custom-scroll space-y-4">
              {pastJobs.length > 0 ? pastJobs.map((pastJob) => (
                <div key={pastJob.id} className="bg-white rounded-xl p-3 flex gap-3 items-center border border-surface-200 hover:border-orange-200 transition-colors shadow-sm">
                  <div className="w-20 h-14 bg-black rounded-lg overflow-hidden relative flex-shrink-0">
                    {pastJob.final_video_url ? (
                      <button
                        onClick={() => setActivePreviewUrl(pastJob.final_video_url)}
                        className="absolute inset-0 block group/video w-full h-full text-left cursor-pointer"
                      >
                        <video src={pastJob.final_video_url + "#t=0.1"} preload="metadata" className="w-full h-full object-cover group-hover/video:scale-105 transition-transform duration-300" />
                        <div className="absolute inset-0 bg-black/20 group-hover/video:bg-black/10 transition-colors flex items-center justify-center">
                          <Film className="w-4 h-4 text-white opacity-100 transition-opacity" />
                        </div>
                      </button>
                    ) : (
                      <div className="absolute inset-0 flex items-center justify-center bg-surface-100">
                        <Film className="w-5 h-5 text-surface-300" />
                      </div>
                    )}
                  </div>
                  <div className="flex-1 min-w-0 text-left">
                    <p className="text-sm font-medium text-surface-900 capitalize mb-0.5 truncate">{pastJob.vibe} Reel</p>
                    <p className="text-xs text-surface-500 truncate">{new Date(pastJob.created_at).toLocaleDateString()}</p>
                  </div>
                  {pastJob.final_video_url && (
                    <button
                      onClick={() => triggerDownload(pastJob.final_video_url)}
                      title="Download Reel"
                      className="p-2 rounded-lg bg-surface-100 text-surface-600 hover:bg-orange-50 hover:text-orange-600 transition-colors cursor-pointer"
                    >
                      <Download className="w-4 h-4" />
                    </button>
                  )}
                </div>
              )) : (
                <div className="text-center py-8">
                  <Film className="w-8 h-8 text-surface-300 mx-auto mb-3" />
                  <p className="text-surface-500 text-sm">No past reels found.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* PHASE: Upload (no media) */}
      {chatPhase === 'upload' && (
        <UploadPhase
          onPickFiles={() => fileInputRef.current?.click()}
          uploading={uploading}
          pastJobs={pastJobs}
          onPreviewReel={setActivePreviewUrl}
        />
      )}

      {/* PHASE: Chat (has media) */}
      {chatPhase !== 'upload' && (
        <>
          {/* Scrollable chat area */}
          <div className="flex-1 overflow-y-auto custom-scroll w-full">
            <div className="px-5 md:px-8 pb-4 pt-4 space-y-6 w-full max-w-[1600px] mx-auto">
              {/* Media grid — always pinned at top of chat */}
              <MediaGrid
                assets={mediaAssets}
                onDelete={deleteAsset}
                onAddMore={() => fileInputRef.current?.click()}
                locked={['song_query', 'processing', 'story', 'rendering', 'complete', 'failed'].includes(chatPhase)}
                uploading={uploading}
              />

              {/* === Vibe question === */}
              {['vibe', 'music', 'song_query', 'processing', 'story', 'rendering', 'complete', 'failed'].includes(chatPhase) && (
                <ChatQuestion
                  question="What vibe are you going for?"
                  answered={chatPhase !== 'vibe'}
                  answeredValue={vibeOptions.find(v => v.value === config.vibe)?.label}
                >
                  {chatPhase === 'vibe' && (
                    <div className="flex flex-wrap gap-2 mt-3">
                      {vibeOptions.map(opt => (
                        <button
                          key={opt.value}
                          onClick={() => handleVibeSelect(opt.value as ConfigState['vibe'])}
                          className="flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-white border border-surface-200 shadow-sm hover:border-orange-400 hover:shadow-md text-sm font-medium text-surface-800 transition-all duration-200 active:scale-95"
                        >
                          <span>{opt.icon}</span>
                          <span>{opt.label}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </ChatQuestion>
              )}

              {/* === Music question === */}
              {['music', 'song_query', 'processing', 'story', 'rendering', 'complete', 'failed'].includes(chatPhase) && (
                <ChatQuestion
                  question="What about background music?"
                  answered={chatPhase !== 'music'}
                  answeredValue={musicModeOptions.find(m => m.value === config.musicMode)?.label}
                >
                  {chatPhase === 'music' && (
                    <div className="flex flex-col gap-2 mt-3">
                      {musicModeOptions.map(opt => (
                        <button
                          key={opt.value}
                          onClick={() => handleMusicSelect(opt.value as ConfigState['musicMode'])}
                          className="flex items-start gap-3 px-4 py-3 rounded-2xl bg-white border border-surface-200 shadow-sm hover:border-orange-400 hover:shadow-md text-left transition-all duration-200 active:scale-[0.98]"
                        >
                          <Volume2 className="w-4 h-4 text-orange-500 flex-shrink-0 mt-0.5" />
                          <div>
                            <span className="block text-sm font-medium text-surface-800">{opt.label}</span>
                            <span className="block text-xs text-surface-500 mt-0.5">{opt.description}</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </ChatQuestion>
              )}

              {/* === Custom Song Query question === */}
              {['song_query', 'processing', 'story', 'rendering', 'complete', 'failed'].includes(chatPhase) && config.musicMode === 'custom' && (
                <ChatQuestion
                  question="Which song or artist would you like to search for?"
                  answered={chatPhase !== 'song_query'}
                  answeredValue={config.songQuery}
                />
              )}

              {/* === Story review card === */}
              {['story', 'processing', 'rendering', 'complete', 'failed'].includes(chatPhase) && job?.story_summary && (
                <StoryCard
                  story={job.story_summary}
                  instruction={rewriteInstruction}
                  onInstructionChange={setRewriteInstruction}
                  editing={editingStory}
                  textareaRef={storyTextareaRef}
                  onEditToggle={() => {
                    setEditingStory(e => !e);
                    if (!editingStory) setTimeout(() => storyTextareaRef.current?.focus(), 50);
                  }}
                  onGenerate={handleConfirmStory}
                  onRegenerate={handleRegenerateStory}
                  confirming={confirming}
                  isRegenerating={isRegenerating}
                  readOnly={chatPhase !== 'story'}
                />
              )}

              {/* === Processing messages === */}
              {chatPhase === 'processing' && (
                <ProcessingBubble messages={analysisMessages} />
              )}
              {chatPhase === 'rendering' && (
                <ProcessingBubble messages={renderMessages} />
              )}

              {/* === Complete: video player === */}
              {chatPhase === 'complete' && job?.final_video_url && (
                <CompletedCard 
                  url={job.final_video_url} 
                  onReset={handleResetAll} 
                  onPreview={() => setActivePreviewUrl(job.final_video_url)} 
                />
              )}

              {/* === Failed === */}
              {chatPhase === 'failed' && (
                <FailedCard message={job?.error_message} onRetry={handleResetAll} />
              )}

              <div ref={chatEndRef} />
            </div>
          </div>

          {/* Bottom chat input bar */}
          <ChatInputBar
            phase={chatPhase}
            value={inputText}
            onChange={setInputText}
            onSend={
              chatPhase === 'song_query' ? handleSendSongQuery : () => {}
            }
            onAddFiles={() => fileInputRef.current?.click()}
          />
        </>
      )}

      {/* ── Custom Fullscreen Video Popup ── */}
      {activePreviewUrl && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          {/* Modal Container */}
          <div className="bg-white rounded-3xl border border-orange-100 shadow-2xl w-full max-w-[360px] flex flex-col overflow-hidden animate-scale-in">
            {/* Header */}
            <div className="px-5 py-3 border-b border-orange-50 flex items-center justify-between bg-orange-50/30">
              <span className="text-xs font-bold text-slate-800 tracking-wide uppercase">Preview Reel</span>
              <button 
                onClick={() => setActivePreviewUrl(null)} 
                className="w-7 h-7 rounded-full bg-white hover:bg-orange-50 text-orange-500 flex items-center justify-center border border-orange-100 transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            
            {/* Video Box - Portrait Only (9:16) */}
            <div className="aspect-[9/16] bg-slate-950 w-full relative">
              <video src={activePreviewUrl} controls autoPlay className="w-full h-full object-contain" />
            </div>
            
            {/* Footer */}
            <div className="p-3.5 flex items-center justify-end bg-slate-50/50 border-t border-slate-100">
              <button
                onClick={() => setActivePreviewUrl(null)}
                className="px-5 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-full text-[11px] font-bold shadow-md shadow-orange-500/10 active:scale-95 transition-all cursor-pointer"
              >
                Close Preview
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function UploadPhase({ onPickFiles, uploading, pastJobs = [], onPreviewReel }: { onPickFiles: () => void; uploading: boolean; pastJobs?: any[]; onPreviewReel: (url: string) => void }) {
  const [dragActive, setDragActive] = useState(false);

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 gap-8 overflow-y-auto pb-10 pt-10 custom-scroll">
      <div className="text-center">
        <h2 className="text-2xl font-semibold text-surface-900 tracking-tight">Start your reel</h2>
        <p className="text-surface-500 mt-1.5 text-sm leading-relaxed">
          Upload your video clips and photos. AI will do the rest.
        </p>
      </div>

      <button
        onClick={onPickFiles}
        onDragOver={e => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={e => {
          e.preventDefault();
          setDragActive(false);
          // files handled via the global input
        }}
        disabled={uploading}
        className={`
          w-full max-w-sm aspect-[4/3] flex-shrink-0 rounded-3xl border-2 border-dashed
          flex flex-col items-center justify-center gap-4
          transition-all duration-300
          ${dragActive
            ? 'border-orange-500 bg-orange-50'
            : 'border-surface-300 bg-white/60 hover:border-orange-400 hover:bg-white/90'}
        `}
      >
        {uploading ? (
          <div className="flex flex-col items-center gap-3">
            <div className="w-10 h-10 border-2 border-surface-200 border-t-orange-500 rounded-full animate-spin" />
            <span className="text-sm text-surface-500">Uploading...</span>
          </div>
        ) : (
          <>
            <div className={`
              w-16 h-16 rounded-2xl flex items-center justify-center
              ${dragActive ? 'bg-orange-500' : 'bg-surface-100'}
              transition-colors
            `}>
              <Plus className={`w-8 h-8 ${dragActive ? 'text-white' : 'text-surface-400'}`} />
            </div>
            <div className="text-center">
              <p className="font-medium text-surface-800">Drop files here</p>
              <p className="text-sm text-surface-400 mt-1">MP4 · MOV · JPG · PNG</p>
            </div>
          </>
        )}
      </button>

      <p className="text-xs text-surface-400 text-center">
        You can upload multiple clips and photos at once
      </p>

      {/* Past Reels */}
      {pastJobs.length > 0 && (
        <div className="w-full max-w-sm mt-8 animate-fade-in border-t border-surface-200 pt-8 pb-4">
          <h3 className="text-lg font-semibold text-surface-900 mb-4 flex items-center gap-2">
            <Film className="w-5 h-5 text-orange-500" />
            Past Reels
          </h3>
          <div className="space-y-4">
            {pastJobs.map((pastJob) => (
              <div key={pastJob.id} className="bg-white rounded-xl p-4 flex gap-4 items-center border border-surface-200 hover:border-orange-200 transition-colors shadow-sm">
                {/* Thumbnail */}
                <div className="w-24 h-16 bg-black rounded-lg overflow-hidden relative flex-shrink-0">
                  {pastJob.final_video_url ? (
                  <button
                    onClick={() => onPreviewReel(pastJob.final_video_url)}
                    className="absolute inset-0 block group/video w-full h-full text-left cursor-pointer"
                  >
                    <video src={pastJob.final_video_url + "#t=0.1"} preload="metadata" className="w-full h-full object-cover group-hover/video:scale-105 transition-transform duration-300" />
                    <div className="absolute inset-0 bg-black/20 group-hover/video:bg-black/10 transition-colors flex items-center justify-center">
                      <Film className="w-6 h-6 text-white opacity-100 transition-opacity" />
                    </div>
                  </button>
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center bg-surface-100">
                      <Film className="w-6 h-6 text-surface-300" />
                    </div>
                  )}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0 text-left">
                  <p className="text-sm font-medium text-surface-900 capitalize mb-1">
                    {pastJob.vibe} Reel
                  </p>
                  <p className="text-xs text-surface-500 truncate">
                    {new Date(pastJob.created_at).toLocaleDateString()}
                  </p>
                </div>

                {/* Actions */}
                {pastJob.final_video_url && (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => triggerDownload(pastJob.final_video_url)}
                      title="Download Reel"
                      className="p-2 rounded-lg bg-surface-100 text-surface-600 hover:bg-orange-50 hover:text-orange-600 transition-colors cursor-pointer"
                    >
                      <Download className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MediaGrid({
  assets,
  onDelete,
  onAddMore,
  locked,
  uploading,
}: {
  assets: MediaAsset[];
  onDelete: (id: string) => void;
  onAddMore: () => void;
  locked: boolean;
  uploading: boolean;
}) {
  return (
    <div className="pt-2 flex justify-end animate-fade-in w-full">
      <div className="w-full max-w-[70%]">
        <div className="flex flex-wrap justify-end gap-1.5">
          {assets.map(asset => (
            <div key={asset.id} className="relative group w-20 h-20 rounded-xl overflow-hidden bg-surface-200">
              {/* Thumbnail */}
              {asset.is_image ? (
                <img
                  src={asset.thumbnail_url || asset.presigned_url || ''}
                  alt={asset.filename}
                  className="w-full h-full object-cover"
                />
              ) : (
                <video
                  src={(asset.thumbnail_url || asset.presigned_url || '') + '#t=0.1'}
                  className="w-full h-full object-cover"
                />
              )}

              {/* Delete overlay */}
              {!locked && (
                <button
                  onClick={() => onDelete(asset.id)}
                  className="absolute top-1 right-1 w-5 h-5 rounded-full bg-black/60 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity z-10"
                >
                  <Trash2 className="w-2.5 h-2.5 text-white" />
                </button>
              )}
            </div>
          ))}

          {/* Add more tile */}
          {!locked && (
            <button
              onClick={onAddMore}
              disabled={uploading}
              className="w-20 h-20 rounded-xl border-2 border-dashed border-surface-300 flex items-center justify-center hover:border-orange-400 hover:bg-white/50 transition-all duration-200 bg-white/30"
            >
              {uploading
                ? <div className="w-4 h-4 border border-surface-300 border-t-orange-500 rounded-full animate-spin" />
                : <Plus className="w-5 h-5 text-surface-400" />
              }
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ChatQuestion({
  question,
  answered,
  answeredValue,
  children,
}: {
  question: string;
  answered: boolean;
  answeredValue?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="animate-slide-up flex flex-col items-start w-full">
      <div className="bg-white rounded-2xl rounded-tl-sm shadow-sm px-4 py-3.5 max-w-[85%] md:max-w-2xl border border-surface-200/60">
        <p className="text-sm text-surface-800 leading-relaxed">{question}</p>
        {answered && answeredValue && (
          <div className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 bg-orange-50 rounded-full">
            <Check className="w-3 h-3 text-orange-500" strokeWidth={3} />
            <span className="text-xs font-medium text-orange-600">{answeredValue}</span>
          </div>
        )}
        {!answered && children && (
          <div className="mt-4">
            {children}
          </div>
        )}
      </div>
    </div>
  );
}

function ProcessingBubble({ messages }: { messages: string[] }) {
  const [msgIndex, setMsgIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  // Reset index when message list changes
  useEffect(() => {
    setMsgIndex(0);
  }, [messages]);

  useEffect(() => {
    const interval = setInterval(() => {
      setVisible(false);
      setTimeout(() => {
        setMsgIndex(i => (i + 1) % messages.length);
        setVisible(true);
      }, 350);
    }, 2500);
    return () => clearInterval(interval);
  }, [messages]);

  return (
    <div className="animate-slide-up space-y-2 flex flex-col items-start w-full">
      <div className="bg-white rounded-2xl rounded-tl-sm shadow-sm px-4 py-2.5 max-w-[85%] border border-surface-200/60">
        <p
          className={`text-[15px] font-medium text-orange-600 transition-opacity duration-300 ${visible ? 'opacity-100' : 'opacity-0'}`}
          style={{ fontStyle: 'italic' }}
        >
          {messages[msgIndex]}
        </p>
      </div>
      <p className="text-xs text-surface-400 pl-1">
        might take a couple of minutes
        <br />
        you can leave and come back later
      </p>
    </div>
  );
}

function StoryCard({
  story,
  instruction,
  onInstructionChange,
  editing,
  textareaRef,
  onEditToggle,
  onGenerate,
  onRegenerate,
  confirming,
  isRegenerating,
  readOnly,
}: {
  story: string;
  instruction: string;
  onInstructionChange: (v: string) => void;
  editing: boolean;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  onEditToggle: () => void;
  onGenerate: () => void;
  onRegenerate: () => void;
  confirming: boolean;
  isRegenerating: boolean;
  readOnly?: boolean;
}) {
  return (
    <div className="animate-slide-up space-y-3 flex flex-col items-start w-full">
      <div className="bg-white rounded-2xl rounded-tl-sm shadow-sm overflow-hidden max-w-[92%] border border-surface-200/60">
        <div className="p-4 relative">
          {isRegenerating && (
            <div className="absolute inset-0 bg-white/60 backdrop-blur-[1px] flex items-center justify-center z-10">
              <div className="w-5 h-5 border-2 border-orange-200 border-t-orange-500 rounded-full animate-spin" />
            </div>
          )}
          <p className="text-sm text-surface-800 leading-relaxed">{story}</p>

          {editing && !readOnly && (
            <div className="mt-4 pt-4 border-t border-surface-100">
              <textarea
                ref={textareaRef}
                value={instruction}
                onChange={e => onInstructionChange(e.target.value)}
                placeholder="Ask AI to make changes (e.g., make it shorter, more emotional...)"
                rows={3}
                className="w-full text-sm text-surface-800 leading-relaxed resize-none focus:outline-none bg-transparent"
              />
            </div>
          )}

          {!editing && !readOnly && (
            <div className="flex items-center gap-4 mt-3">
              <button
                onClick={onEditToggle}
                disabled={isRegenerating}
                className="flex items-center gap-1.5 text-xs text-orange-500 hover:text-orange-600 transition-colors font-medium disabled:opacity-50"
              >
                <Pencil className="w-3 h-3" />
                Ask AI to change story
              </button>
              
              <button
                onClick={onRegenerate}
                disabled={isRegenerating}
                className="flex items-center gap-1.5 text-xs text-surface-500 hover:text-surface-700 transition-colors font-medium disabled:opacity-50"
              >
                <RefreshCw className="w-3 h-3" />
                Regenerate description
              </button>
            </div>
          )}
        </div>

        {!readOnly && (
          <div className="border-t border-surface-100 px-4 py-2.5 flex items-center gap-2 text-xs text-surface-400">
            <Volume2 className="w-3.5 h-3.5" />
            <span>this story will guide your video's narrative</span>
          </div>
        )}
      </div>

      {/* Action buttons */}
      {!readOnly && (
        <div className="flex items-center gap-3 pl-1">
          <button
            onClick={onGenerate}
            disabled={confirming}
            className="flex items-center gap-2 px-5 py-2.5 bg-orange-600 text-white rounded-full text-sm font-semibold shadow-sm hover:bg-orange-700 disabled:opacity-60 transition-all duration-200 active:scale-95"
          >
            {confirming && <div className="w-3.5 h-3.5 border border-white/40 border-t-white rounded-full animate-spin" />}
            {editing && instruction.trim() ? 'Rewrite & Generate' : 'Generate'}
          </button>
        </div>
      )}
    </div>
  );
}

function CompletedCard({ url, onReset, onPreview }: { url: string; onReset: () => void; onPreview: () => void }) {
  const [downloading, setDownloading] = useState(false);
 
  const handleDownload = async () => {
    setDownloading(true);
    await triggerDownload(url);
    setDownloading(false);
  };
 
  return (
    <div className="animate-slide-up space-y-4 max-w-[92%] sm:max-w-[340px] flex flex-col items-center w-full mx-auto sm:mx-0">
      <div className="bg-white rounded-3xl shadow-lg border border-orange-100/60 overflow-hidden w-full">
        {/* Video Container - Portrait (9:16) */}
        <div className="aspect-[9/16] bg-slate-950 relative group">
          <video src={url} controls className="w-full h-full object-contain" />
          
          {/* Custom Fullscreen Trigger Button overlay */}
          <button
            onClick={onPreview}
            className="absolute top-3 right-3 z-10 w-9 h-9 rounded-full bg-black/60 hover:bg-black/80 text-white flex items-center justify-center transition-all opacity-0 group-hover:opacity-100 cursor-pointer"
            title="Open Preview Popup"
          >
            <Maximize2 className="w-4 h-4 text-white" />
          </button>
        </div>
        
        <div className="p-4.5 flex items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-bold text-slate-900 truncate">Your reel is ready!</p>
            <p className="text-[11px] font-semibold text-slate-400 mt-0.5">Tap to watch or download</p>
          </div>
          <button
            onClick={handleDownload}
            disabled={downloading}
            className="flex items-center gap-1.5 px-4.5 py-2 bg-orange-500 hover:bg-orange-600 disabled:bg-orange-400 text-white rounded-full text-xs font-bold shadow-md shadow-orange-500/10 active:scale-95 transition-all cursor-pointer flex-shrink-0"
          >
            {downloading ? (
              <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <Download className="w-3.5 h-3.5" />
            )}
            Save
          </button>
        </div>
      </div>
 
      <button
        onClick={onReset}
        className="flex items-center gap-2 px-5 py-2.5 rounded-full bg-white shadow-sm border border-slate-200 text-xs font-bold text-slate-600 hover:border-orange-400 hover:text-orange-500 transition-all cursor-pointer"
      >
        <RotateCcw className="w-3.5 h-3.5" />
        Make another version
      </button>
    </div>
  );
}

function FailedCard({ message, onRetry }: { message?: string | null; onRetry: () => void }) {
  return (
    <div className="animate-slide-up flex flex-col items-start w-full">
      <div className="bg-white rounded-2xl rounded-tl-sm shadow-sm px-4 py-4 max-w-[85%] space-y-3">
        <p className="text-sm font-medium text-error-600">Something went wrong</p>
        {message && <p className="text-xs text-surface-500">{message}</p>}
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 px-4 py-2 bg-surface-900 text-white rounded-full text-sm font-medium hover:bg-surface-700 transition-colors"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          Try again
        </button>
      </div>
    </div>
  );
}

function ChatInputBar({
  phase,
  value,
  onChange,
  onSend,
  onAddFiles,
}: {
  phase: ChatPhase;
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onAddFiles: () => void;
}) {
  const getPlaceholder = () => {
    if (phase === 'song_query') return 'Type your song or artist...';
    if (phase === 'story') return 'Type to edit...';
    if (phase === 'complete') return 'Ask for changes...';
    return 'Message...';
  };

  const isDisabled = ['song_query', 'processing', 'rendering', 'complete', 'failed'].includes(phase);

  return (
    <div className="px-4 pb-4 pt-2 flex items-center gap-2.5 border-t border-surface-200/50 bg-transparent">
      {/* Add files button */}
      <button
        onClick={onAddFiles}
        disabled={isDisabled}
        className="w-9 h-9 rounded-full bg-white shadow-sm border border-surface-200 flex items-center justify-center flex-shrink-0 hover:border-orange-400 disabled:opacity-40 transition-all"
      >
        <Plus className="w-4 h-4 text-surface-600" />
      </button>

      {/* Text input */}
      <div className="flex-1 bg-white rounded-full shadow-sm border border-surface-200 px-4 py-2.5">
        <input
          type="text"
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && value.trim()) onSend(); }}
          placeholder={getPlaceholder()}
          disabled={isDisabled}
          className="w-full text-sm text-surface-800 placeholder:text-surface-400 bg-transparent focus:outline-none disabled:opacity-40"
        />
      </div>

      {/* Send button */}
      <button
        onClick={onSend}
        disabled={isDisabled || !value.trim()}
        className="w-9 h-9 rounded-full bg-white shadow-sm border border-surface-200 flex items-center justify-center flex-shrink-0 hover:border-orange-400 hover:bg-orange-50 disabled:opacity-40 transition-all"
      >
        <Send className="w-4 h-4 text-surface-600" />
      </button>
    </div>
  );
}
