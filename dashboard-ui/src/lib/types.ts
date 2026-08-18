// Mirrors scripts/dashboard.py's emit_json() shape EXACTLY (camelCase, same nesting).
// Python is the source of truth for this shape - if the two drift, trust Python and fix
// these types, never the reverse. See scripts/dashboard.py's `_project_json`/`_engagement_json`/
// `_session_json`/`emit_json` for the authoritative serialization.

export type EngagementStatus = 'in_progress' | 'blocked' | 'closing' | 'closed'
export type ArtifactStatus = 'interim' | 'final'
export type ProjectBasis = 'config' | 'fingerprint' | 'explicit' | 'historical'
export type ConsentOutcome = 'asked' | 'declined' | null

export interface Artifact {
  path: string
  absPath: string | null // resolved against the engagement's pack dir - use lib/links.ts's
  // fileUrl() to turn this into a clickable file:// href, never build the URI by hand
  title: string
  status: ArtifactStatus
  added: string | null // ISO date
}

export interface ClosingEmail {
  name: string
  absPath: string
}

export interface CostRollup {
  sessionCount: number
  tokensIn: number
  tokensOut: number
  cacheRead: number
  cacheWrite: number
  costUsd: number
  costPartial: boolean // true when at least one matched session had usage from a model
  // not in the pricing table (scripts/dashboard.py's _MODEL_PRICING_PER_MTOK) - costUsd is
  // then a floor, not the full figure
}

export interface Engagement {
  slug: string
  dir: string | null
  title: string | null
  status: EngagementStatus | 'invalid'
  profile: string | null
  opened: string | null // ISO date
  closed: string | null // ISO date
  outstanding: number
  pendingRatifications: number
  consentOutcome: ConsentOutcome
  team: string[] // "Name (role-slug)" pairs
  artifacts: Artifact[]
  settingsSnapshot: Record<string, unknown> | null
  log: string[] // dated free-text notes - see lib/timelineModel.ts for the two line shapes
  // 🧠 inferred (scripts/dashboard.py's _match_engagement/_engagement_cost_rollup):
  // sessions are matched to this engagement by date falling inside opened->closed, not a
  // hard link. null when no known session's date falls in this engagement's window.
  costRollup: CostRollup | null
}

export interface ToolProbe {
  installed: number
  total: number
  fresh: boolean
}

export interface HookWiring {
  wired: number
  installed: number
  total: number
}

export interface Project {
  name: string
  path: string
  version: string | null
  branch: string | null
  basis: ProjectBasis
  preferences: { docx: boolean; citations: boolean }
  toolProbe: ToolProbe | null
  hookWiring: HookWiring | null
  archivedCount: number
  emails: ClosingEmail[]
  gateFindings: string[]
  consentOpen: boolean
  mapPath: string | null
  mapFindings: string[] | null
  engagements: Engagement[]
}

export interface ModelCostBreakdown {
  in: number
  out: number
  cacheRead: number
  cacheWrite: number
  costUsd: number
}

export interface SessionUsage {
  session: string
  date: string
  in: number
  out: number
  cacheRead: number
  cacheWrite: number
  badLines: number
  spanSeconds: number
  costUsd: number // list-price estimate, see CostRollup.costPartial for the same caveat
  costPartial: boolean
  // 🧠 inferred date-range match (scripts/dashboard.py's _match_engagement) - null means no
  // known engagement's opened->closed window contains this session's date ("Unattributed").
  engagementSlug: string | null
  // Per-model split of this session's usage - outer key is the raw model id ("unknown" when
  // a message carried no model field at all, e.g. very old transcripts; a present-but-unpriced
  // model like "<synthetic>" buckets under its own literal string instead).
  costByModel: Record<string, ModelCostBreakdown>
}

export interface CostByModelRow {
  model: string
  in: number
  out: number
  cacheRead: number
  cacheWrite: number
  costUsd: number
}

export interface ProjectUsage {
  sessions: SessionUsage[]
  unparsableFiles: number
  totalSeconds: number
}

export interface ObligationSource {
  project: string
  slug: string | null
  title: string | null
}

export interface ObligationRow {
  citation: string
  count: number
  verified: boolean
  sources: ObligationSource[] // distinct (project, engagement) pairs that cited this obligation
}

export interface DashboardData {
  generated: string
  roleLabels: Record<string, string>
  projects: Project[]
  usageByProject: Record<string, ProjectUsage>
  costByModel: CostByModelRow[] // machine-wide, every known session, sorted by cost descending
  obligations: ObligationRow[]
}
