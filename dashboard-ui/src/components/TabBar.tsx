export type TabKey = 'engagements' | 'portfolio' | 'sessions'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'engagements', label: 'Engagements' },
  { key: 'portfolio', label: 'Portfolio' },
  { key: 'sessions', label: 'Sessions & cost' },
]

interface TabBarProps {
  active: TabKey
  onChange: (tab: TabKey) => void
}

// The page-level IA fix (docs/adr/ADR-013 revision): the session/cost table is ops
// telemetry, categorically different from delivery tracking, and belongs on its own screen -
// not stacked under a single engagement card, which is what produced the "long list of
// sessions and only one engagement is confusing" feedback. Plain useState, no router needed
// for three static views.
export function TabBar({ active, onChange }: TabBarProps) {
  return (
    <div
      className="my-4 inline-flex max-w-full flex-wrap gap-0.5 rounded-full bg-surface-1 p-1"
      role="tablist"
    >
      {TABS.map((t) => (
        <button
          key={t.key}
          role="tab"
          type="button"
          className={`shrink-0 whitespace-nowrap rounded-full px-3 py-2 text-sm font-semibold transition-colors duration-150 sm:px-4 ${
            active === t.key ? 'bg-accent text-[var(--actor-text)]' : 'text-muted hover:text-fg'
          }`}
          aria-selected={active === t.key}
          onClick={() => onChange(t.key)}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}
