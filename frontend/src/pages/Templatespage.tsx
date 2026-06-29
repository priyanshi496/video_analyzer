// src/pages/TemplatesPage.tsx  (or src/pages/templates/index.tsx — match your router convention)
//
// Add route in your router:
//   <Route path="/templates" element={<TemplatesPage />} />

import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { TemplatePicker } from '../components/workspace/TemplatePicker'
import { TemplateEditor } from '../components/workspace/TemplateEditor'
import type { VideoTemplate } from '../services/templates'
import type { MediaAsset } from '../components/workspace/TemplateEditor'
import { projectService } from '../services/projects'

// ── You need these two pieces of context: ───────────────────────────────────
//   1. The current project ID (from URL params / your project store)
//   2. The media assets already uploaded to that project
//
// Replace these with however your app already exposes them.
// If you use Zustand, do: const { currentProject, mediaAssets } = useProjectStore()
// If you use React Router params, do: const { projectId } = useParams()
// ────────────────────────────────────────────────────────────────────────────

import { useParams } from 'react-router-dom'  // adjust import if needed

// Implement real hook using projectService.listMedia
function useProjectAssets(projectId: string): MediaAsset[] {
  const [assets, setAssets] = useState<MediaAsset[]>([])

  useEffect(() => {
    if (!projectId) return
    projectService.listMedia(projectId)
      .then(m => setAssets(m || []))
      .catch(err => console.error('Failed to list project media assets:', err))
  }, [projectId])

  return assets;
}

export default function TemplatesPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const mediaAssets = useProjectAssets(projectId ?? '')
  const [selected, setSelected] = useState<VideoTemplate | null>(null)

  return (
    <div className="h-screen bg-[#0a0a0a] overflow-hidden">
      <AnimatePresence mode="wait">
        {!selected ? (
          <motion.div
            key="picker"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2 }}
            className="h-full overflow-y-auto px-6 py-8"
          >
            <TemplatePicker onSelect={setSelected} />
          </motion.div>
        ) : (
          <motion.div
            key="editor"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            transition={{ duration: 0.2 }}
            className="h-full"
          >
            <TemplateEditor
              template={selected}
              projectId={projectId ?? ''}
              mediaAssets={mediaAssets}
              onBack={() => setSelected(null)}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}