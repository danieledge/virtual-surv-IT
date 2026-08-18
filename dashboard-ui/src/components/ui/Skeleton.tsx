import { cn } from './cn'

export interface SkeletonProps {
  className?: string
  /** CSS width/height, e.g. "8rem" or "100%". Defaults to a small block. */
  width?: string
  height?: string
}

/**
 * Loading placeholder - Tailwind's `animate-pulse`. `prefers-reduced-motion` safety is not
 * re-implemented here: the existing global rule at the bottom of index.css
 * (`@media (prefers-reduced-motion: reduce) { * { animation-duration: 0.001ms !important; ... } }`)
 * already catches every animation in the app, Tailwind's included, so it applies automatically.
 */
export function Skeleton({ className, width, height }: SkeletonProps) {
  return (
    <div
      className={cn('animate-pulse rounded-lg bg-surface-3', className)}
      style={{ width: width ?? '100%', height: height ?? '1rem' }}
      aria-hidden="true"
    />
  )
}
