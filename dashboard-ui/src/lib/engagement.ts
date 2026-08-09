// Small engagement-row helpers, ported from scripts/dashboard.py (_day_span, _settings_chips,
// _STATUS_MARK) - kept as pure functions so EngagementRow stays a thin render layer.

export function daySpan(opened: string | null, closed: string | null): string | null {
  if (!opened) return null
  const o = new Date(`${opened}T00:00:00Z`)
  if (Number.isNaN(o.getTime())) return null
  if (closed) {
    const c = new Date(`${closed}T00:00:00Z`)
    if (Number.isNaN(c.getTime())) return null
    const days = Math.round((c.getTime() - o.getTime()) / 86400000)
    return `${days}d`
  }
  const now = new Date()
  const todayUtc = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  const days = Math.round((todayUtc - o.getTime()) / 86400000)
  return `${days}d so far`
}

const PREF_LABELS: [key: string, label: string][] = [
  ['regulatory_citations', 'citations'],
  ['large_context_review_split', 'review-split'],
  ['parallel_dispatch_via_workflow', 'workflow-dispatch'],
  ['map_skeleton', 'map-skeleton'],
]

export interface SettingsChip {
  label: string
  on: boolean
}

/** settingsSnapshot's OWN keys stay Python snake_case (emit_json only camelCases the outer
 * envelope, not this pass-through blob) - accessed directly here, not re-cased. */
export function settingsChips(snapshot: Record<string, unknown> | null): SettingsChip[] | null {
  if (!snapshot) return null
  const extraFormats = Array.isArray(snapshot.extra_formats) ? snapshot.extra_formats : []
  const chips: SettingsChip[] = [{ label: 'docx', on: extraFormats.includes('docx') }]
  for (const [key, label] of PREF_LABELS) {
    chips.push({ label, on: Boolean(snapshot[key]) })
  }
  return chips
}

export const STATUS_MARK: Record<string, { icon: string; tone?: 'ok' | 'warn' | 'bad' }> = {
  in_progress: { icon: '⏳' }, // ⏳
  blocked: { icon: '⛔', tone: 'warn' }, // ⛔
  closing: { icon: '\u{1F512}' }, // 🔒
  closed: { icon: '✅', tone: 'ok' }, // ✅
  invalid: { icon: '❗', tone: 'bad' }, // ❗
}
