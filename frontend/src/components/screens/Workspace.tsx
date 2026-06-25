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
  | 'directives'   // optional instructions
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
}

const processingMessages = [
  'Generating script.',
  'Cooking up your next viral cut.',
  'Syncing vibe, voice, and visuals.',
  'Analyzing your best moments.',
  'Stitching the story together.',
  'Matching beats to your clips.',
  'Finding the perfect sequence.',
];

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
    uploadFile,
    deleteAsset,
    startGeneration,
    confirmStory,
    resetJob,
  } = useWorkspace(projectId || '');

  const pastJobs = jobHistory?.filter((h: any) => h.id !== job?.id && h.status === 'COMPLETED') || [];

  const [chatPhase, setChatPhase] = useState<ChatPhase>('upload');
  const [showPastReels, setShowPastReels] = useState(false);
  const [config, setConfig] = useState<ConfigState>({
    vibe: 'cinematic',
    musicMode: 'ai-catalog',
    instrumentalOnly: false,
    directives: '',
  });
  const [rewriteInstruction, setRewriteInstruction] = useState('');
  const [editingStory, setEditingStory] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [inputText, setInputText] = useState('');

  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const storyTextareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatPhase, job?.status]);

  // Advance phase after first upload
  useEffect(() => {
    if (mediaAssets.length > 0 && chatPhase === 'upload') {
      setChatPhase('vibe');
    }
  }, [mediaAssets.length, chatPhase]);

  // Sync job status to chat phase
  useEffect(() => {
    if (!job) return;

    if (job.status === 'PENDING' || (job.status === 'RUNNING' && chatPhase !== 'rendering')) {
      setChatPhase('processing');
    } else if (job.status === 'STORY_PROPOSED') {
      setChatPhase('story');
    } else if (job.status === 'RUNNING' && chatPhase === 'rendering') {
      // stay in rendering
    } else if (job.status === 'COMPLETED') {
      setChatPhase('complete');
    } else if (job.status === 'FAILED') {
      setChatPhase('failed');
    }
  }, [job?.status]);

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
    setConfig(prev => ({ ...prev, musicMode }));
    setTimeout(() => setChatPhase('directives'), 400);
  };

  const handleStartGeneration = async (directives = '') => {
    setConfig(prev => ({ ...prev, directives }));
    const finalConfig: GenerationConfig = { ...config, directives };
    await startGeneration(finalConfig);
  };

  const handleSkipDirectives = () => {
    handleStartGeneration('');
  };

  const handleSendDirectives = () => {
    handleStartGeneration(inputText.trim());
    setInputText('');
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
    <div className="flex-1 flex flex-col bg-transparent overflow-hidden min-h-0">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="video/*,image/*"
        className="hidden"
        onChange={handleFileSelect}
      />

      {/* Top bar */}
      <div className="flex items-center justify-between px-5 py-3.5 bg-transparent">
        <button
          onClick={onBack}
          className="w-9 h-9 rounded-full bg-surface-200/80 flex items-center justify-center hover:bg-surface-300/80 transition-colors"
        >
          <ArrowLeft className="w-4 h-4 text-surface-700" />
        </button>
        <span className="text-sm font-medium text-surface-600 truncate max-w-[200px]">
          {project?.name || 'Project'}
        </span>
        <button 
          onClick={() => setShowPastReels(true)}
          className="w-9 h-9 rounded-full bg-surface-200/80 flex items-center justify-center hover:bg-surface-300/80 transition-colors"
        >
          <MoreHorizontal className="w-4 h-4 text-surface-700" />
        </button>
      </div>

      {/* Past Reels Modal */}
      {showPastReels && (
        <div className="absolute inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
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
                      <a href={pastJob.final_video_url} target="_blank" rel="noreferrer" className="absolute inset-0 block group/video">
                        <video src={pastJob.final_video_url + "#t=0.1"} preload="metadata" className="w-full h-full object-cover group-hover/video:scale-105 transition-transform duration-300" />
                        <div className="absolute inset-0 bg-black/20 group-hover/video:bg-black/10 transition-colors flex items-center justify-center">
                          <Film className="w-4 h-4 text-white opacity-0 group-hover/video:opacity-100 transition-opacity" />
                        </div>
                      </a>
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
                    <a href={pastJob.final_video_url} download title="Download Reel" className="p-2 rounded-lg bg-surface-100 text-surface-600 hover:bg-orange-50 hover:text-orange-600 transition-colors">
                      <Download className="w-4 h-4" />
                    </a>
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
                locked={['processing', 'rendering', 'complete', 'failed'].includes(chatPhase)}
                uploading={uploading}
              />

              {/* === Vibe question === */}
              {['vibe', 'music', 'directives', 'processing', 'story', 'rendering', 'complete', 'failed'].includes(chatPhase) && (
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
              {['music', 'directives', 'processing', 'story', 'rendering', 'complete', 'failed'].includes(chatPhase) && (
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

              {/* === Directives / story brief === */}
              {['directives', 'processing', 'story', 'rendering', 'complete', 'failed'].includes(chatPhase) && (
                <ChatQuestion
                  question="Any story or instructions for the AI? (optional)"
                  answered={chatPhase !== 'directives'}
                  answeredValue={config.directives || 'Skipped — AI decides'}
                >
                  {chatPhase === 'directives' && (
                    <div className="mt-3 flex gap-2">
                      <button
                        onClick={handleSkipDirectives}
                        className="px-5 py-2 rounded-full bg-white border border-surface-200 shadow-sm hover:border-orange-400 text-sm text-surface-600 font-medium transition-all duration-200 active:scale-95"
                      >
                        Skip
                      </button>
                      <button
                        onClick={handleSendDirectives}
                        disabled={!inputText.trim()}
                        className="px-5 py-2 rounded-full bg-orange-600 text-white text-sm font-medium shadow-sm disabled:opacity-40 hover:bg-orange-700 transition-all duration-200 active:scale-95"
                      >
                        Use my story
                      </button>
                    </div>
                  )}
                </ChatQuestion>
              )}

              {/* === Processing messages === */}
              {(chatPhase === 'processing' || chatPhase === 'rendering') && (
                <ProcessingBubble />
              )}

              {/* === Story review card === */}
              {['story', 'rendering', 'complete', 'failed'].includes(chatPhase) && job?.story_summary && (
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
                  confirming={confirming}
                  readOnly={chatPhase !== 'story'}
                />
              )}

              {/* === Complete: video player === */}
              {chatPhase === 'complete' && job?.final_video_url && (
                <CompletedCard url={job.final_video_url} onReset={handleResetAll} />
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
            onSend={handleSendDirectives}
            onAddFiles={() => fileInputRef.current?.click()}
          />
        </>
      )}
    </div>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function UploadPhase({ onPickFiles, uploading, pastJobs = [] }: { onPickFiles: () => void; uploading: boolean; pastJobs?: any[] }) {
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
                    <a href={pastJob.final_video_url} target="_blank" rel="noreferrer" className="absolute inset-0 block group/video">
                      <video src={pastJob.final_video_url + "#t=0.1"} preload="metadata" className="w-full h-full object-cover group-hover/video:scale-105 transition-transform duration-300" />
                      <div className="absolute inset-0 bg-black/20 group-hover/video:bg-black/10 transition-colors flex items-center justify-center">
                        <Film className="w-6 h-6 text-white opacity-0 group-hover/video:opacity-100 transition-opacity" />
                      </div>
                    </a>
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
                    <a
                      href={pastJob.final_video_url}
                      download
                      title="Download Reel"
                      className="p-2 rounded-lg bg-surface-100 text-surface-600 hover:bg-orange-50 hover:text-orange-600 transition-colors"
                    >
                      <Download className="w-4 h-4" />
                    </a>
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

function ProcessingBubble() {
  const [msgIndex, setMsgIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const interval = setInterval(() => {
      setVisible(false);
      setTimeout(() => {
        setMsgIndex(i => (i + 1) % processingMessages.length);
        setVisible(true);
      }, 350);
    }, 2500);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="animate-slide-up space-y-2 flex flex-col items-start w-full">
      <div className="bg-white rounded-2xl rounded-tl-sm shadow-sm px-4 py-2.5 max-w-[85%] border border-surface-200/60">
        <p
          className={`text-[15px] font-medium text-orange-600 transition-opacity duration-300 ${visible ? 'opacity-100' : 'opacity-0'}`}
          style={{ fontStyle: 'italic' }}
        >
          {processingMessages[msgIndex]}
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
  confirming,
  readOnly,
}: {
  story: string;
  instruction: string;
  onInstructionChange: (v: string) => void;
  editing: boolean;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  onEditToggle: () => void;
  onGenerate: () => void;
  confirming: boolean;
  readOnly?: boolean;
}) {
  return (
    <div className="animate-slide-up space-y-3 flex flex-col items-start w-full">
      <div className="bg-white rounded-2xl rounded-tl-sm shadow-sm overflow-hidden max-w-[92%] border border-surface-200/60">
        <div className="p-4">
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
            <button
              onClick={onEditToggle}
              className="flex items-center gap-1.5 mt-3 text-xs text-orange-500 hover:text-orange-600 transition-colors font-medium"
            >
              <Pencil className="w-3 h-3" />
              Ask AI to change story
            </button>
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

function CompletedCard({ url, onReset }: { url: string; onReset: () => void }) {
  return (
    <div className="animate-slide-up space-y-4 max-w-[92%] md:max-w-[400px] flex flex-col items-start w-full">
      <div className="bg-white rounded-2xl rounded-tl-sm shadow-sm overflow-hidden w-full">
        <div className="aspect-video bg-surface-900">
          <video src={url} controls className="w-full h-full object-contain" />
        </div>
        <div className="p-4 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-surface-900">Your reel is ready!</p>
            <p className="text-xs text-surface-500 mt-0.5">Tap to watch or download</p>
          </div>
          <a
            href={url}
            download
            className="flex items-center gap-1.5 px-4 py-2 bg-orange-600 text-white rounded-full text-sm font-medium hover:bg-orange-700 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            Save
          </a>
        </div>
      </div>

      <button
        onClick={onReset}
        className="flex items-center gap-2 px-4 py-2 rounded-full bg-white shadow-sm border border-surface-200 text-sm text-surface-600 hover:border-orange-400 transition-all"
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
    if (phase === 'directives') return 'Share your story, or leave it blank...';
    if (phase === 'story') return 'Type to edit...';
    if (phase === 'complete') return 'Ask for changes...';
    return 'Message...';
  };

  const isDisabled = ['processing', 'rendering', 'complete', 'failed'].includes(phase);

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
