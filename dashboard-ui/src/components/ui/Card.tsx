import type { HTMLAttributes } from 'react'
import { cn } from './cn'

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Adds the border/background hover transition (for clickable/navigable cards). */
  hover?: boolean
}

/**
 * Shared card surface - `bg-surface-2` + `border-border` + the project's existing 16px radius
 * (`rounded-2xl`, matching `--radius-lg` exactly). Not yet wired into any page (round 2/3 does
 * that); this is the primitive those rounds build on.
 */
export function Card({ hover = false, className, children, ...rest }: CardProps) {
  return (
    <div className={cn(hover ? 'ui-card-hover' : 'ui-card', 'p-4', className)} {...rest}>
      {children}
    </div>
  )
}
