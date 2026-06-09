import { staticFile } from "remotion";

export function resolveAsset(src: string): string {
  if (
    src.startsWith("http://") ||
    src.startsWith("https://") ||
    src.startsWith("data:")
  ) {
    return src;
  }
  const clean = src.replace(/^file:\/\/\/?/, "");
  
  // Resolve absolute paths matching local project folders (symlinked in /public)
  const idx = clean.indexOf("/video_analyzer/");
  if (idx !== -1) {
    const rel = clean.substring(idx + "/video_analyzer/".length);
    return staticFile(rel);
  }
  
  for (const dir of ["input_videos", "projects", "clips"]) {
    const dIdx = clean.indexOf("/" + dir + "/");
    if (dIdx !== -1) {
      return staticFile(clean.substring(dIdx + 1));
    }
  }

  if (clean.startsWith("/") || /^[A-Za-z]:[/\\]/.test(clean)) {
    return `file:///${clean.replace(/\\/g, "/")}`;
  }
  return staticFile(clean);
}
