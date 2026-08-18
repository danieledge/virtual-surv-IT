import type { ReactNode } from 'react'
import { useDefaultOpen } from '../../hooks/useDefaultOpen'

export interface CcCollapsibleProps {
  title: ReactNode
  /** A short always-visible glance stat shown next to the title, even collapsed - e.g. Cost by
      Agent's total, or Engagement State's loop/error counts. Collapsing a section must never
      hide the fact that there's something worth opening. */
  peek?: ReactNode
  ariaLabel: string
  children: ReactNode
  className?: string
}

// Native <details>/<summary> disclosure, open by default on desktop/tablet and collapsed by
// default on phone (useDefaultOpen) - the fix for "even the metrics at the beginning require
// significant scroll" (2026-08-09 live feedback): the Command Centre used to stack its full
// desktop content order unconditionally on phone, so reaching anything below the header meant
// scrolling past every section above it. No library - same <details> pattern already used by
// EngagementTimeline.tsx elsewhere in this app, just with a per-breakpoint initial state instead
// of always-collapsed.
export function CcCollapsible({ title, peek, ariaLabel, children, className }: CcCollapsibleProps) {
  const defaultOpen = useDefaultOpen()
  return (
    <details className={['cc-panel', 'cc-collapsible', className].filter(Boolean).join(' ')} open={defaultOpen}>
      <summary className="cc-collapsible-summary" aria-label={ariaLabel}>
        <span className="cc-collapsible-chevron" aria-hidden="true" />
        <h2 className="cc-panel-title cc-collapsible-title">{title}</h2>
        {peek !== undefined && <span className="cc-collapsible-peek">{peek}</span>}
      </summary>
      <div className="cc-collapsible-body">{children}</div>
    </details>
  )
}
