// src/components/workspace/TemplatePicker.tsx
import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Play, Clock, Layers, Music, Grid2X2, LayoutTemplate } from 'lucide-react'
import templatesService from '../../services/templates'
import type { VideoTemplate } from '../../services/templates'

interface TemplatePickerProps {
  onSelect: (template: VideoTemplate) => void
  onClose?: () => void
}

function TemplateCard({ template, onSelect }: { template: VideoTemplate; onSelect: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [hovered, setHovered] = useState(false)
  const previewUrl = template.preview_url
  const thumbnailUrl = (template as any).thumbnail_url
  const isBeatGrid = template.layout_mode === 'beat_grid'

  const totalDuration = template.slots.reduce((s, sl) => {
    const slotTracks = (template as any).tracks?.filter((t: any) => t.slot_id === sl.id && t.type === 'video') || []
    const dur = sl.duration_seconds ?? (slotTracks.length > 0 ? Math.max(...slotTracks.map((t: any) => t.end - t.start)) : 5.0)
    return s + dur
  }, 0)

  useEffect(() => {
    if (!videoRef.current || !previewUrl) return
    if (hovered) videoRef.current.play().catch(() => {})
    else { videoRef.current.pause(); videoRef.current.currentTime = 0 }
  }, [hovered, previewUrl])

  return (
    <motion.div
      className="group relative rounded-2xl overflow-hidden bg-[#0f0f0f] border border-white/10 cursor-pointer"
      whileHover={{ scale: 1.02 }}
      transition={{ duration: 0.15, ease: 'easeOut' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onSelect}
    >
      {/* Thumbnail area — 9:16 ratio */}
      <div className="relative overflow-hidden bg-[#1a1a1a]" style={{ aspectRatio: '9/14' }}>
        {previewUrl ? (
          <video
            ref={videoRef}
            src={previewUrl}
            poster={thumbnailUrl}
            className="w-full h-full object-cover"
            loop playsInline preload="metadata"
          />
        ) : (
          /* Visual placeholder — shows the layout type */
          <div className="w-full h-full flex flex-col items-center justify-center gap-4">
            {isBeatGrid ? (
              <BeatGridPreview />
            ) : (
              <div className="flex flex-col items-center gap-2 opacity-40">
                <LayoutTemplate className="w-10 h-10 text-white" />
                <span className="text-white/50 text-xs">{template.slots.length} clips</span>
              </div>
            )}
          </div>
        )}

        {/* Play overlay */}
        <motion.div
          className="absolute inset-0 bg-black/40 flex items-center justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: hovered ? 1 : 0 }}
          transition={{ duration: 0.12 }}
        >
          <div className="w-12 h-12 rounded-full bg-white/15 backdrop-blur-sm border border-white/20 flex items-center justify-center">
            <Play className="w-5 h-5 text-white ml-0.5" fill="white" />
          </div>
        </motion.div>

        {/* Layout badge */}
        <div className="absolute top-2.5 left-2.5 flex items-center gap-1 bg-black/60 backdrop-blur-sm text-white/90 text-[10px] font-semibold px-2 py-1 rounded-full border border-white/10">
          {isBeatGrid ? <Grid2X2 className="w-3 h-3" /> : <Layers className="w-3 h-3" />}
          {isBeatGrid ? 'Beat Grid' : `${template.slots.length} clips`}
        </div>
      </div>

      {/* Card info */}
      <div className="p-3">
        <h3 className="font-semibold text-white text-sm leading-tight">{template.name}</h3>
        <p className="text-white/40 text-xs mt-1 line-clamp-2 leading-relaxed">{template.description}</p>

        <div className="flex items-center gap-1.5 mt-2.5 flex-wrap">
          <Pill icon={<Clock className="w-3 h-3" />} label={`${totalDuration}s`} />
          <Pill icon={<Music className="w-3 h-3" />} label="AI music" />
          <Pill label={template.aspect_ratio} />
        </div>
      </div>

      {/* CTA */}
      <motion.div
        className="px-3 pb-3"
        initial={{ opacity: 0 }}
        animate={{ opacity: hovered ? 1 : 0 }}
        transition={{ duration: 0.12 }}
      >
        <button
          className="w-full bg-orange-500 hover:bg-orange-400 text-white text-xs font-bold py-2.5 rounded-xl transition-colors"
          onClick={e => { e.stopPropagation(); onSelect() }}
        >
          Use this template
        </button>
      </motion.div>
    </motion.div>
  )
}

function Pill({ icon, label }: { icon?: React.ReactNode; label: string }) {
  return (
    <span className="flex items-center gap-1 text-[10px] text-white/40 bg-white/5 border border-white/10 px-2 py-0.5 rounded-full">
      {icon}{label}
    </span>
  )
}

/** Animated 2×2 grid preview that plays in the card thumbnail */
function BeatGridPreview() {
  const [step, setStep] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setStep(s => (s + 1) % 8), 600)
    return () => clearInterval(id)
  }, [])

  // steps 0-2: fullscreen blink, steps 3-6: grid cells appear
  const isGrid = step >= 3
  const cellsVisible = isGrid ? step - 2 : 0

  return (
    <div className="w-3/4 h-3/4 relative">
      {!isGrid ? (
        <motion.div
          key={step}
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="w-full h-full rounded-lg bg-gradient-to-br from-orange-500/20 to-orange-500/5 border border-orange-500/20"
        />
      ) : (
        <div className="w-full h-full grid grid-cols-2 gap-1">
          {[0,1,2,3].map(i => (
            <motion.div
              key={i}
              initial={{ scale: 0.75, opacity: 0 }}
              animate={i < cellsVisible ? { scale: 1, opacity: 1 } : { scale: 0.75, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 400, damping: 20 }}
              className="rounded bg-gradient-to-br from-orange-500/30 to-orange-500/10 border border-orange-500/25"
            />
          ))}
        </div>
      )}
      <div className="absolute bottom-1 right-1 text-[9px] text-white/30 font-mono">
        {isGrid ? `${cellsVisible}/4` : `${step + 1}/3`}
      </div>
    </div>
  )
}

export function TemplatePicker({ onSelect }: TemplatePickerProps) {
  const [templates, setTemplates] = useState<VideoTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    templatesService.getTemplates()
      .then(setTemplates)
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
      {[1,2,3].map(i => (
        <div key={i} className="rounded-2xl bg-white/5 animate-pulse" style={{ aspectRatio: '9/16' }} />
      ))}
    </div>
  )

  if (error) return (
    <div className="flex flex-col items-center justify-center py-20 text-white/30 text-sm">
      Could not load templates
    </div>
  )

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white tracking-tight">Templates</h2>
        <p className="text-white/40 text-sm mt-1">Pick a style — add your clips — get your reel</p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {templates.map(t => (
          <TemplateCard key={t.id} template={t} onSelect={() => onSelect(t)} />
        ))}
      </div>
    </div>
  )
}