import type { ReactNode } from 'react'
import { cn } from './cn'

export interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: ReactNode
  className?: string
}

/**
 * Replaces ad hoc `<p className="muted">No X found.</p>` one-liners scattered across
 * Portfolio/Sessions/Command Centre with one consistent empty-state treatment. Not wired into
 * any of those spots yet - round 2/3 does that.
 */
export function EmptyState({ icon, title, description, className }: EmptyStateProps) {
  return (
    <div className={cn('ui-card', 'flex flex-col items-center gap-2 p-8 text-center', className)}>
      {icon && (
        <span className="text-muted" aria-hidden="true">
          {icon}
        </span>
      )}
      <p className="font-semibold text-fg">{title}</p>
      {description && <p className="max-w-sm text-sm text-muted">{description}</p>}
    </div>
  )
}
