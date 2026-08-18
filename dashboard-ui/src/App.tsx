import { useCallback, useState } from 'react'
import { Moon, Sun, SunMoon } from 'lucide-react'
import rawData from '../data/dashboard-data.json'
import type { DashboardData } from './lib/types'
import { KpiStrip } from './components/KpiStrip'
import { EngagementExplorer } from './components/EngagementExplorer'
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

interface NavTarget {
  project: string
  slug: string
}

function App() {
  const [tab, setTab] = useState<TabKey>('engagements')
  const { theme, cycleTheme } = useTheme()
  const ThemeIcon = THEME_ICON[theme]
  // Portfolio/Sessions -> Engagements cross-linking (2026-08-08, "portfolio feels disjointed
  // from the page that actually shows engagements"): switch to the Engagements tab and select
  // the target engagement there. EngagementExplorer (2026-08-09, master-detail redesign) owns
  // turning this into visible feedback itself - selecting IS the navigation now, so there's no
  // separate scroll+flash step to coordinate here.
  const [navTarget, setNavTarget] = useState<NavTarget | null>(null)

  const goToEngagement = useCallback((project: string, slug: string) => {
    setTab('engagements')
    setNavTarget({ project, slug })
  }, [])

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
            <h2 className="mb-2 mt-2">Engagements</h2>
            <EngagementExplorer
              projects={data.projects}
              roleLabels={data.roleLabels}
              navTarget={navTarget}
              onNavConsumed={() => setNavTarget(null)}
            />
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
