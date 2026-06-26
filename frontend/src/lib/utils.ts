export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '0 B';
  if (bytes === 0) return '0 B';

  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export function formatDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffMinutes = Math.floor(diffMs / (1000 * 60));

  if (diffMinutes < 1) return 'Just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
  });
}

export function generateId(): string {
  return Math.random().toString(36).slice(2, 11);
}

export function getFileType(file: File): 'video' | 'image' | 'unknown' {
  if (file.type.startsWith('video/')) return 'video';
  if (file.type.startsWith('image/')) return 'image';
  return 'unknown';
}

export const vibeOptions = [
  { value: 'cinematic', label: 'Cinematic', icon: '🎬', description: 'Film-like quality with dramatic pacing' },
  { value: 'energetic', label: 'Energetic', icon: '⚡', description: 'Fast-paced, bold transitions and hype' },
  { value: 'romantic', label: 'Romantic', icon: '💕', description: 'Soft, slow, and emotional narrative' },
  { value: 'spiritual', label: 'Spiritual', icon: '🕊️', description: 'Calm, serene, and uplifting' },
  { value: 'garba', label: 'Garba', icon: '🪘', description: 'Festive, rhythmic, and traditional' },
];

export const musicModeOptions = [
  { value: 'ai', label: 'AI Catalog Match', description: 'AI picks the perfect track from our library' },
  { value: 'suno', label: 'Suno Generation', description: 'Generate custom music with AI' },
  { value: 'custom', label: 'Custom Song Query', description: 'Search for a specific song' },
  { value: 'none', label: 'No Music', description: 'Original audio only' },
];

export const triggerDownload = async (url: string, filename: string = 'reel.mp4') => {
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
