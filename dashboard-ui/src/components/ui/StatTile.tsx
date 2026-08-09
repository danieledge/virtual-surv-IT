import type { ReactNode } from 'react'
import { cn } from './cn'

export type StatTileTone = 'accent' | 'ok' | 'warn' | 'bad'

export interface StatTileProps {
  label: string
  value: ReactNode
  subLabel?: ReactNode
  icon?: ReactNode
  tone?: StatTileTone
  className?: string
}

const TONE_TEXT: Record<StatTileTone, string> = {
  accent: 'text-accent',
  ok: 'text-ok',
  warn: 'text-warn',
  bad: 'text-bad',
}

/**
 * KpiStrip-style tile: label + big value + optional sub-label/icon. Structural equivalent of
 * the existing `.kpi`/`.kpi-value`/`.kpi-label` rules in index.css, rebuilt on the shared
 * `ui-card` surface + Tailwind utilities so KpiStrip can move onto it in round 2.
 */
export function StatTile({ label, value, subLabel, icon, tone = 'accent', className }: StatTileProps) {
  return (
    <div className={cn('ui-card', 'flex flex-col items-center gap-1 p-3 text-center', className)}>
      {icon && (
        <span className="text-lg leading-none" aria-hidden="true">
          {icon}
        </span>
      )}
      <span className={cn('text-2xl font-extrabold leading-tight tracking-tight tabular-nums', TONE_TEXT[tone])}>
        {value}
      </span>
      <span className="text-[0.68rem] font-semibold uppercase tracking-wide text-muted">{label}</span>
      {subLabel && <span className="text-xs text-muted">{subLabel}</span>}
    </div>
  )
}
