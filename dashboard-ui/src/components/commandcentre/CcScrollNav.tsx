import { useEffect, useState, type RefObject } from 'react'

export interface CcScrollNavProps {
  scrollRef: RefObject<HTMLDivElement | null>
  /** Content-local x positions (same coordinate space as the scroll container's `scrollLeft`)
      to jump between - e.g. each pulse marker's pixel offset, or each timeline block's `x`.
      Prev/Next always land exactly on a real moment instead of an arbitrary drag position. */
  stops: number[]
  label: string
}

// Real, always-visible touch affordance for a horizontally-scrolling area - NOT a styled native
// scrollbar. `::-webkit-scrollbar` (this app's only prior scrollbar styling, in index.css) is a
// Chromium/desktop-WebKit pseudo-element iOS Safari does not implement at all, which is exactly
// why the Engagement Pulse strip and Agent Timeline looked fine in every headless-Chrome check
// this project ran but weren't actually easy to use on a real iPhone (2026-08-09 live feedback,
// confirmed via screenshots from the user's own phone). A hand-built progress bar + explicit
// Prev/Next buttons render identically everywhere, including iOS Safari, and don't depend on
// drag precision at all - tap once, land exactly on the next real moment.
//
// CSS scroll-snap was the first idea (see the plan) but doesn't apply here: both scrollers'
// content is either absolutely-positioned (<div>s in EngagementPulse) or a single SVG element
// (AgentTimeline) - neither produces the in-flow child elements scroll-snap-align requires as
// snap targets. This component gets the same real outcome (land precisely on a moment, no fine
// drag needed) a different way.
export function CcScrollNav({ scrollRef, stops, label }: CcScrollNavProps) {
  const [progress, setProgress] = useState(0)
  const [hasOverflow, setHasOverflow] = useState(false)

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    const update = () => {
      const max = el.scrollWidth - el.clientWidth
      setHasOverflow(max > 4)
      setProgress(max > 0 ? el.scrollLeft / max : 0)
    }
    update()

    el.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      el.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [scrollRef])

  const jump = (direction: 1 | -1) => {
    const el = scrollRef.current
    if (!el || stops.length === 0) return
    const current = el.scrollLeft
    const sorted = [...stops].sort((a, b) => a - b)
    const target =
      direction === 1
        ? (sorted.find((s) => s > current + 4) ?? sorted[sorted.length - 1]!)
        : ([...sorted].reverse().find((s) => s < current - 4) ?? sorted[0]!)
    el.scrollTo({ left: Math.max(target - 24, 0), behavior: 'smooth' })
  }

  // Nothing to scroll (fits on screen, e.g. a wide desktop viewport) - no dead controls shown.
  if (!hasOverflow) return null

  return (
    <div className="cc-scroll-nav" role="group" aria-label={`${label} scroll position`}>
      <button
        type="button"
        className="cc-scroll-nav-btn"
        onClick={() => jump(-1)}
        aria-label={`Jump to the previous ${label} moment`}
      >
        ‹
      </button>
      <span className="cc-scroll-nav-track" aria-hidden="true">
        <span className="cc-scroll-nav-fill" style={{ width: `${Math.round(progress * 100)}%` }} />
      </span>
      <button
        type="button"
        className="cc-scroll-nav-btn"
        onClick={() => jump(1)}
        aria-label={`Jump to the next ${label} moment`}
      >
        ›
      </button>
    </div>
  )
}
