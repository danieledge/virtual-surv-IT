// One place to turn an absolute filesystem path (from Python's emit_json - see
// scripts/dashboard.py's _artifact_json/_project_json) into a clickable file:// href.
// encodeURI (not encodeURIComponent) - it leaves "/" intact while escaping spaces and other
// characters a bare path can legally contain but a URI can't.
export function fileUrl(absPath: string | null | undefined): string | null {
  if (!absPath) return null
  return `file://${encodeURI(absPath)}`
}

// Stable per-engagement DOM id, shared by EngagementRow (sets it) and the Portfolio/Sessions
// cross-linking (App.goToEngagement scrolls to it) - sanitized so a project path or slug with
// spaces/slashes never produces an invalid id.
export function engagementAnchorId(project: string, slug: string): string {
  const clean = (s: string) => s.replace(/[^a-zA-Z0-9_-]+/g, '-')
  return `eng-${clean(project)}-${clean(slug)}`
}
