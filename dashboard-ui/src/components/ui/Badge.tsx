import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from './cn'

export type BadgeTone = 'ok' | 'bad' | 'warn' | 'neutral'

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone
  icon?: ReactNode
}

const TONE_CLASS: Record<BadgeTone, string> = {
  ok: 'badge-ok',
  bad: 'badge-bad',
  warn: 'badge-warn',
  neutral: 'badge-neutral',
}

/**
 * Status pill - tones match the existing `--ok`/`--bad`/`--warn` semantic tokens (same colors
 * already used for `.ok`/`.bad`/`.warn` text and `.kpi-value.ok`/`.warn` elsewhere in the app),
 * so a badge and existing status text always agree.
 */
export function Badge({ tone = 'neutral', icon, className, children, ...rest }: BadgeProps) {
  return (
    <span className={cn(TONE_CLASS[tone], className)} {...rest}>
      {icon}
      {children}
    </span>
  )
}
