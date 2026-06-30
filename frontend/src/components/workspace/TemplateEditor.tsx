// src/components/workspace/TemplateEditor.tsx
import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft, CheckCircle2, Loader2, Download,
  AlertCircle, X, Grid2X2, Layers, Film, Type
} from 'lucide-react'
import { api } from '../../services/api'
import templatesService from '../../services/templates'
import type { VideoTemplate } from '../../services/templates'

// ── Types ──────────────────────────────────────────────────────────────────

export interface MediaAsset {
  id: string
  filename: string
  thumbnail_url?: string
  duration?: number
}

interface Assignment {
  slot_id: string
  media_asset_id: string | null
  text: string
}

interface TemplateEditorProps {
  template: VideoTemplate
  projectId: string
  mediaAssets: MediaAsset[]
  onBack: () => void
  onRender?: (slots: Array<{ slot_id: string; media_asset_id: string | null; text: string | null }>) => void
}

// ── Section divider label ──────────────────────────────────────────────────

function SectionLabel({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-2 px-1 py-2">
      <div className="text-white/30">{icon}</div>
      <span className="text-[10px] font-bold text-white/30 uppercase tracking-widest">{label}</span>
      <div className="flex-1 h-px bg-white/10" />
    </div>
  )
}

// ── Slot row ───────────────────────────────────────────────────────────────

function SlotRow({
  index, slot, assignment, isActive, assets, duration,
  onActivate, onClear, onTextChange, textTrack,
}: {
  index: number
  slot: VideoTemplate['slots'][0]
  assignment: Assignment
  isActive: boolean
  assets: MediaAsset[]
  duration: number
  onActivate: () => void
  onClear: () => void
  onTextChange: (text: string) => void
  textTrack?: { placeholder: string; editable: boolean }
}) {
  const filled = !!assignment.media_asset_id
  const asset = filled ? assets.find(a => a.id === assignment.media_asset_id) : null
  const label = slot.label
  const placeholder = textTrack?.placeholder || (slot as any).text_overlay?.placeholder || `Caption for clip ${index + 1}…`
  const editable = textTrack ? textTrack.editable : (slot as any).text_overlay?.editable !== false

  return (
    <div className="rounded-xl overflow-hidden">
      <div
        onClick={onActivate}
        className={`
          relative flex items-center gap-2.5 px-3 py-2.5 border cursor-pointer transition-all
          ${isActive
            ? 'border-orange-500/60 bg-orange-500/10 rounded-t-xl'
            : filled
              ? 'border-white/10 bg-white/5 hover:bg-white/8 rounded-xl'
              : 'border-dashed border-white/15 bg-white/2 hover:bg-white/5 rounded-xl'
          }
        `}
      >
        {/* Step number or check */}
        <div className="flex-shrink-0 w-6 h-6 flex items-center justify-center">
          {filled
            ? <CheckCircle2 className="w-5 h-5 text-orange-400" />
            : <div className={`w-5 h-5 rounded-full border flex items-center justify-center text-[11px] font-bold
                ${isActive ? 'border-orange-400 text-orange-400' : 'border-white/20 text-white/20'}`}>
                {index + 1}
              </div>
          }
        </div>

        {/* Label + meta */}
        <div className="flex-1 min-w-0">
          <p className={`text-xs font-medium truncate ${isActive ? 'text-orange-300' : 'text-white/70'}`}>
            {label || `Clip ${index + 1}`}
          </p>
          <p className="text-[10px] text-white/30 mt-0.5">
            {duration}s · {slot.transition_out || 'cut'}
            {assignment.text ? <span className="text-white/40 ml-1.5">· "{assignment.text.slice(0, 18)}{assignment.text.length > 18 ? '…' : ''}"</span> : null}
          </p>
        </div>

        {/* Assigned clip thumbnail with text overlay */}
        {filled && asset && (
          <div className="flex-shrink-0 relative group/thumb">
            <div className="w-10 h-10 rounded-lg overflow-hidden bg-white/10 relative">
              {asset.thumbnail_url
                ? <img src={asset.thumbnail_url} alt="" className="w-full h-full object-cover" />
                : <div className="w-full h-full flex items-center justify-center">
                    <Film className="w-4 h-4 text-white/30" />
                  </div>
              }
              {/* Mini text overlay preview on thumbnail */}
              {assignment.text && (
                <div className="absolute inset-0 flex items-end justify-center pb-0.5 px-0.5">
                  <span className="text-white text-[5px] font-medium leading-tight text-center drop-shadow-[0_1px_2px_rgba(0,0,0,0.9)] line-clamp-2">
                    {assignment.text}
                  </span>
                </div>
              )}
            </div>
            <button
              onClick={e => { e.stopPropagation(); onClear() }}
              className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-white/20 rounded-full
                flex items-center justify-center opacity-0 group-hover/thumb:opacity-100 transition-opacity"
            >
              <X className="w-2.5 h-2.5 text-white" />
            </button>
          </div>
        )}

        {/* Active indicator */}
        {isActive && (
          <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-orange-400 rounded-full" />
        )}
      </div>

      {/* Expanded text input when slot is active */}
      <AnimatePresence>
        {isActive && editable && (
          <motion.div
            key="text-input"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="overflow-hidden"
          >
            <div className="px-3 py-2 bg-orange-500/8 border-x border-b border-orange-500/30 rounded-b-xl">
              <div className="flex items-center gap-1.5 mb-1">
                <Type className="w-3 h-3 text-orange-400/70" />
                <span className="text-[9px] font-bold uppercase tracking-widest text-orange-400/60">Text overlay</span>
              </div>
              <input
                type="text"
                value={assignment.text}
                onChange={e => onTextChange(e.target.value)}
                onClick={e => e.stopPropagation()}
                placeholder={placeholder}
                maxLength={80}
                className="w-full bg-transparent text-white/90 text-xs placeholder-white/20
                  outline-none border-b border-white/10 focus:border-orange-500/50 pb-1
                  transition-colors caret-orange-400"
              />
              {assignment.text && (
                <p className="text-[9px] text-white/25 mt-1 text-right">{assignment.text.length}/80</p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── Main ───────────────────────────────────────────────────────────────────

export function TemplateEditor({ template, projectId, mediaAssets, onBack, onRender }: TemplateEditorProps) {
  const sections = template.sections as Array<{ mode: string; slots: Array<{ id: string }> }> | undefined

  // Build a map of slot_id → text track info (placeholder + editable) from tracks
  const textTrackMap = useMemo(() => {
    const tracks = (template as any).tracks as Array<any> | undefined
    const map: Record<string, { placeholder: string; editable: boolean }> = {}
    tracks?.forEach(t => {
      if (t.type === 'text' && t.slot_id && t.content) {
        map[t.slot_id] = {
          placeholder: t.content.placeholder ?? '',
          editable: t.content.editable !== false,
        }
      }
    })
    return map
  }, [template])

  const [assignments, setAssignments] = useState<Assignment[]>(
    // Pre-fill text with the lyric placeholder from text tracks
    template.slots.map(s => ({
      slot_id: s.id,
      media_asset_id: null,
      text: (template as any).tracks
        ?.find((t: any) => t.type === 'text' && t.slot_id === s.id)
        ?.content?.placeholder ?? '',
    }))
  )
  const [activeSlot, setActiveSlot] = useState(template.slots[0]?.id ?? '')
  const [status, setStatus] = useState<'idle' | 'pending' | 'processing' | 'done' | 'error'>('idle')
  const [progress, setProgress] = useState(0)
  const [jobId, setJobId] = useState<string | null>(null)
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const filledCount = assignments.filter(a => a.media_asset_id !== null).length
  const totalSlots = template.slots.length
  const allFilled = filledCount === totalSlots

  function assignToActive(assetId: string) {
    setAssignments(prev => prev.map(a =>
      a.slot_id === activeSlot ? { ...a, media_asset_id: assetId } : a
    ))
    // Auto-advance to next empty slot
    const next = template.slots.find(s =>
      s.id !== activeSlot &&
      !assignments.find(a => a.slot_id === s.id)?.media_asset_id &&
      !(s.id === activeSlot) // not the one we just filled
    )
    if (next) setActiveSlot(next.id)
  }

  async function handleRender() {
    const slotsPayload = assignments.map(a => ({
      slot_id: a.slot_id,
      media_asset_id: a.media_asset_id,
      text: a.text || null,
    }))

    if (onRender) {
      onRender(slotsPayload)
      return
    }

    setStatus('pending')
    setProgress(0)
    try {
      const job = await templatesService.renderFromTemplate(
        projectId,
        template.id,
        slotsPayload
      )
      setJobId(job.id)
    } catch {
      setStatus('error')
    }
  }

  useEffect(() => {
    if (!jobId) return
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await api.get(`/jobs/${jobId}`)
        setProgress(data.progress ?? 0)
        if (data.status === 'COMPLETED') {
          setStatus('done')
          setDownloadUrl(data.final_video_url)
          clearInterval(pollRef.current!)
        } else if (data.status === 'FAILED') {
          setStatus('error')
          clearInterval(pollRef.current!)
        } else {
          setStatus('processing')
        }
      } catch {
        setStatus('error')
        clearInterval(pollRef.current!)
      }
    }, 2000)
    return () => clearInterval(pollRef.current!)
  }, [jobId])

  // Group slots by section for display
  const slotsBySection: Array<{ label: string; icon: React.ReactNode; slotIds: string[] }> = sections
    ? sections.map(sec => ({
        label: sec.mode === 'fullscreen' ? 'Fullscreen build-up' : 'Grid drop',
        icon: sec.mode === 'fullscreen' ? <Layers className="w-3.5 h-3.5" /> : <Grid2X2 className="w-3.5 h-3.5" />,
        slotIds: sec.slots.map(s => s.id),
      }))
    : [{ label: 'Clips', icon: <Layers className="w-3.5 h-3.5" />, slotIds: template.slots.map(s => s.id) }]

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full bg-[#0a0a0a]">

      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 bg-[#111] border-b border-white/8 flex-shrink-0">
        <button onClick={onBack}
          className="p-1.5 rounded-lg hover:bg-white/8 transition-colors text-white/50 hover:text-white">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1 min-w-0">
          <h2 className="font-semibold text-white text-sm truncate">{template.name}</h2>
          <p className="text-[11px] text-white/35 truncate">{template.description}</p>
        </div>
        {/* Fill progress */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-xs text-white/40 tabular-nums font-mono">{filledCount}/{totalSlots}</span>
          <div className="w-16 h-1 bg-white/10 rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-orange-500 rounded-full"
              animate={{ width: `${(filledCount / totalSlots) * 100}%` }}
              transition={{ type: 'spring', stiffness: 280, damping: 28 }}
            />
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left — slots */}
        <div className="w-60 flex-shrink-0 flex flex-col bg-[#111] border-r border-white/8 overflow-hidden">
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {slotsBySection.map((section, si) => (
              <div key={si}>
                <SectionLabel icon={section.icon} label={section.label} />
                {section.slotIds.map(slotId => {
                  const slot = template.slots.find(s => s.id === slotId)!
                  const asgn = assignments.find(a => a.slot_id === slotId)!
                  const globalIdx = template.slots.findIndex(s => s.id === slotId)
                  
                  // Calculate duration from tracks if duration_seconds is missing
                  const slotTracks = (template as any).tracks?.filter((t: any) => t.slot_id === slotId && t.type === 'video') || []
                  const duration = slot.duration_seconds ?? (slotTracks.length > 0 ? Math.max(...slotTracks.map((t: any) => t.end - t.start)) : 5.0)

                  return (
                    <SlotRow
                      key={slotId}
                      index={globalIdx}
                      slot={slot}
                      assignment={asgn}
                      isActive={activeSlot === slotId}
                      assets={mediaAssets}
                      duration={duration}
                      textTrack={textTrackMap[slotId]}
                      onActivate={() => setActiveSlot(slotId)}
                      onClear={() => setAssignments(prev => prev.map(a =>
                        a.slot_id === slotId ? { ...a, media_asset_id: null } : a
                      ))}
                      onTextChange={text => setAssignments(prev => prev.map(a =>
                        a.slot_id === slotId ? { ...a, text } : a
                      ))}
                    />
                  )
                })}
              </div>
            ))}
          </div>

          {/* Render / status */}
          <div className="p-3 border-t border-white/8 flex-shrink-0">
            <AnimatePresence mode="wait">

              {status === 'done' && (
                <motion.a key="dl" href={downloadUrl!} download
                  initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                  className="flex items-center justify-center gap-2 w-full bg-green-500 hover:bg-green-400
                    text-white font-bold py-3 rounded-xl transition-colors text-sm">
                  <Download className="w-4 h-4" />Download reel
                </motion.a>
              )}

              {status === 'error' && (
                <motion.div key="err" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-2">
                  <div className="flex items-center justify-center gap-1.5 text-red-400 text-xs py-1">
                    <AlertCircle className="w-3.5 h-3.5" />Render failed
                  </div>
                  <button onClick={() => setStatus('idle')}
                    className="w-full py-2.5 rounded-xl bg-white/8 hover:bg-white/12 text-white/60 text-sm transition-colors">
                    Try again
                  </button>
                </motion.div>
              )}

              {(status === 'pending' || status === 'processing') && (
                <motion.div key="prog" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-2">
                  <div className="flex items-center justify-between text-xs text-white/40">
                    <span className="flex items-center gap-1.5">
                      <Loader2 className="w-3 h-3 animate-spin text-orange-400" />
                      {status === 'pending' ? 'Starting…' : 'Rendering…'}
                    </span>
                    <span className="font-mono tabular-nums">{progress}%</span>
                  </div>
                  <div className="w-full h-1 bg-white/10 rounded-full overflow-hidden">
                    <motion.div className="h-full bg-orange-500 rounded-full"
                      animate={{ width: `${progress}%` }} transition={{ duration: 0.4 }} />
                  </div>
                </motion.div>
              )}

              {status === 'idle' && (
                <motion.button key="btn"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                  onClick={handleRender} disabled={!allFilled}
                  className={`w-full py-3 rounded-xl font-bold text-sm transition-all
                    ${allFilled
                      ? 'bg-orange-500 hover:bg-orange-400 text-white'
                      : 'bg-white/5 text-white/20 cursor-not-allowed'
                    }`}
                >
                  {allFilled
                    ? 'Render reel →'
                    : `${totalSlots - filledCount} slot${totalSlots - filledCount !== 1 ? 's' : ''} left`
                  }
                </motion.button>
              )}

            </AnimatePresence>
          </div>
        </div>

        {/* Right — media library */}
        <div className="flex-1 overflow-y-auto bg-[#0a0a0a] p-4">
          <p className="text-[10px] font-bold text-white/25 uppercase tracking-widest mb-3">
            Your clips — click to assign to active slot
          </p>

          {/* Active slot hint */}
          {activeSlot && (
            <div className="mb-3 px-3 py-2 bg-orange-500/10 border border-orange-500/20 rounded-xl">
              <p className="text-xs text-orange-300">
                Assigning to: <span className="font-semibold">
                  {(template.slots.find(s => s.id === activeSlot) as any)?.label || `Slot ${template.slots.findIndex(s => s.id === activeSlot) + 1}`}
                </span>
              </p>
            </div>
          )}

          {mediaAssets.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 text-white/25 text-center">
              <Film className="w-8 h-8 mb-2 opacity-40" />
              <p className="text-sm font-medium">No clips in this project</p>
              <p className="text-xs mt-1 opacity-60">Upload videos first, then come back</p>
            </div>
          ) : (
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
              {mediaAssets.map(asset => {
                const usedIn = assignments.find(a => a.media_asset_id === asset.id)
                const isUsed = !!usedIn
                const usedSlotIndex = isUsed
                  ? template.slots.findIndex(s => s.id === usedIn!.slot_id) + 1
                  : null

                return (
                  <motion.button
                    key={asset.id}
                    onClick={() => assignToActive(asset.id)}
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    style={{ aspectRatio: '1' }}
                    className={`
                      relative rounded-xl overflow-hidden border transition-all
                      ${isUsed
                        ? 'border-orange-500/60 ring-1 ring-orange-500/30'
                        : 'border-white/8 hover:border-white/20'
                      }
                    `}
                  >
                    {asset.thumbnail_url ? (
                      <img src={asset.thumbnail_url} alt={asset.filename} className="w-full h-full object-cover" />
                    ) : asset.presigned_url ? (
                      asset.is_image ? (
                        <img src={asset.presigned_url} alt={asset.filename} className="w-full h-full object-cover" />
                      ) : (
                        <video src={asset.presigned_url + '#t=0.1'} className="w-full h-full object-cover" muted playsInline />
                      )
                    ) : (
                      <div className="w-full h-full bg-white/5 flex items-center justify-center">
                        <Film className="w-5 h-5 text-white/20" />
                      </div>
                    )}

                    {asset.duration && (
                      <div className="absolute bottom-1 right-1 bg-black/70 text-white text-[9px] font-mono px-1 py-0.5 rounded">
                        {Math.round(asset.duration)}s
                      </div>
                    )}

                    {isUsed && (
                      <div className="absolute top-1 left-1 w-5 h-5 bg-orange-500 rounded-full flex items-center justify-center text-[10px] font-bold text-white">
                        {usedSlotIndex}
                      </div>
                    )}
                  </motion.button>
                )
              })}
            </div>
          )}
        </div>

      </div>
    </div>
  )
}