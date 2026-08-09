import { useCallback, useEffect, useMemo, useState } from 'react'
import { Moon, Sun, SunMoon } from 'lucide-react'
import rawData from '../data/dashboard-data.json'
import type { DashboardData } from './lib/types'
import { engagementAnchorId } from './lib/links'
import { KpiStrip } from './components/KpiStrip'
import { ProjectCard } from './components/ProjectCard'
import { Heatmap } from './components/Heatmap'
import { RosterBars } from './components/RosterBars'
import { ObligationTable } from './components/ObligationTable'
import { CostByModelTable } from './components/CostByModelTable'
import { SessionsView } from './components/SessionsView'
import { TabBar, type TabKey } from './components/TabBar'
import { Card } from './components/ui/Card'
import { Button } from './components/ui/Button'
import { useTheme, type ThemeChoice } from './hooks/useTheme'

const THEME_ICON: Record<ThemeChoice, typeof Sun> = { system: SunMoon, light: Sun, dark: Moon }
const THEME_LABEL: Record<ThemeChoice, string> = {
  system: 'Matching your device',
  light: 'Light theme',
  dark: 'Dark theme',
}
const THEME_NEXT_LABEL: Record<ThemeChoice, string> = { system: 'light', light: 'dark', dark: 'matching your device' }

// Statically imported at BUILD time (Vite bundles a JSON import into the JS, no runtime
// fetch) - this is what lets `npm run dashboard` produce a single dist/index.html that works
// opened directly via file://, no server. Regenerate with `npm run data` (or the combined
// `npm run dashboard`, which also rebuilds).
const data = rawData as unknown as DashboardData

const HIGHLIGHT_MS = 2200

interface NavTarget {
  project: string
  slug: string
}

function App() {
  const [tab, setTab] = useState<TabKey>('engagements')
  const { theme, cycleTheme } = useTheme()
  const ThemeIcon = THEME_ICON[theme]
  // Portfolio/Sessions -> Engagements cross-linking (2026-08-08, "portfolio feels disjointed
  // from the page that actually shows engagements"): switch to the Engagements tab, scroll
  // the target row into view, and flash it briefly so the click's effect is visible even
  // when the row was already on screen. An engagement is always inside its project (2026-08-09
  // - there used to be a second, freestanding "Engagement Command Centre" section up here with
  // its own picker; removed, since it just duplicated the one below with no real link between
  // them) - so "go to an engagement" always means "open its project, open its row".
  const [navTarget, setNavTarget] = useState<NavTarget | null>(null)

  const goToEngagement = useCallback((project: string, slug: string) => {
    setTab('engagements')
    setNavTarget({ project, slug })
  }, [])

  useEffect(() => {
    if (!navTarget || tab !== 'engagements') return
    const el = document.getElementById(engagementAnchorId(navTarget.project, navTarget.slug))
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    const timer = setTimeout(() => setNavTarget(null), HIGHLIGHT_MS)
    return () => clearTimeout(timer)
  }, [navTarget, tab])

  // Project search (2026-08-09, "projects collapsed and searchable by default") - filters by
  // project name or any of its engagements' title/slug, so searching for an engagement finds
  // the project it lives in too, not just an exact project-name match.
  const [projectSearch, setProjectSearch] = useState('')
  const projectSearchQuery = projectSearch.trim().toLowerCase()
  const filteredProjects = useMemo(() => {
    if (!projectSearchQuery) return data.projects
    return data.projects.filter(
      (p) =>
        p.name.toLowerCase().includes(projectSearchQuery) ||
        p.engagements.some(
          (e) =>
            e.slug.toLowerCase().includes(projectSearchQuery) ||
            (e.title ?? '').toLowerCase().includes(projectSearchQuery),
        ),
    )
  }, [projectSearchQuery])

  return (
    <>
      <a
        href="#main-content"
        className="absolute -top-12 left-3 z-[100] rounded-lg border border-border-strong bg-surface-5 px-4 py-2 font-semibold text-fg no-underline transition-[top] duration-150 focus:top-3"
      >
        Skip to content
      </a>
      <div className="mx-auto max-w-[76rem] px-3 pb-12 pt-4 sm:px-6 sm:pb-16 sm:pt-8" id="main-content">
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2 border-b-2 border-border-strong pb-2">
          <h1 className="text-xl sm:text-[1.7rem]">🎬 Team dashboard</h1>
          <Button
            type="button"
            variant="ghost"
            onClick={cycleTheme}
            className="shrink-0"
            title={`${THEME_LABEL[theme]} - click for ${THEME_NEXT_LABEL[theme]}`}
          >
            <ThemeIcon size={16} aria-hidden="true" />
            <span className="sr-only">
              Theme: {THEME_LABEL[theme]}. Click to switch to {THEME_NEXT_LABEL[theme]}.
            </span>
          </Button>
        </div>
        <p className="mb-4 mt-0.5 text-sm text-muted">
          A read-only, local look at what the team&apos;s been up to - generated {data.generated}.
        </p>
        <KpiStrip projects={data.projects} obligations={data.obligations} usageByProject={data.usageByProject} />
        <TabBar active={tab} onChange={setTab} />

        {tab === 'engagements' && (
          <>
            <div className="mb-2 mt-2 flex flex-wrap items-center justify-between gap-2">
              <h2 className="!m-0">Projects</h2>
              <label className="relative">
                <span className="sr-only">Search projects and engagements</span>
                <input
                  type="search"
                  value={projectSearch}
                  onChange={(event) => setProjectSearch(event.target.value)}
                  placeholder="Search projects or engagements…"
                  className="w-56 rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-fg placeholder:text-muted focus:border-border-strong focus:outline-none sm:w-72"
                />
              </label>
            </div>
            <p className="sub muted mb-3">
              Expand a project to see its engagements, expand an engagement for its full detail -
              real roster, handoffs and review-loop rework, at day-granularity (no per-second
              timing, confidence scores, or conversation text - not recorded anywhere today).
            </p>
            {data.projects.length === 0 ? (
              <p className="text-muted">No team projects found.</p>
            ) : filteredProjects.length === 0 ? (
              <p className="text-muted">No project or engagement matches &quot;{projectSearch.trim()}&quot;.</p>
            ) : (
              filteredProjects.map((p) => (
                <ProjectCard
                  key={p.path}
                  project={p}
                  roleLabels={data.roleLabels}
                  highlightSlug={navTarget?.project === p.name ? navTarget.slug : null}
                  forceOpen={projectSearchQuery.length > 0}
                />
              ))
            )}
          </>
        )}

        {tab === 'portfolio' && (
          <>
            <h2>Portfolio</h2>
            <Card className="my-4">
              <h3>Activity</h3>
              <Heatmap projects={data.projects} />
            </Card>
            <Card className="my-4">
              <h3>Roster involvement</h3>
              <RosterBars projects={data.projects} onNavigate={goToEngagement} />
            </Card>
            <Card className="my-4">
              <h3>Obligation coverage</h3>
              <ObligationTable rows={data.obligations} onNavigate={goToEngagement} />
            </Card>
          </>
        )}

        {tab === 'sessions' && (
          <>
            <h2>Measured token usage, session time &amp; estimated cost</h2>
            <Card className="my-4">
              <h3>Cost by model</h3>
              <CostByModelTable rows={data.costByModel} />
            </Card>
            <SessionsView
              usageByProject={data.usageByProject}
              projects={data.projects}
              onNavigate={goToEngagement}
            />
          </>
        )}

        <p className="mt-6 text-xs leading-relaxed text-muted">
          This page sees only this machine, and only sessions whose transcripts remain on disk.
          It is read-only by design: management actions (granting consent, running engagements)
          stay deliberate human acts in the terminal. Regenerate with{' '}
          <code>npm run dashboard</code> (dashboard-ui/), or{' '}
          <code>python -m scripts.dashboard --out dashboard.html</code> for the plain no-Node
          fallback.
        </p>
      </div>
    </>
  )
}

export default App
