import { useState } from 'react'

// Picks a one-time INITIAL open/closed state for a native <details> disclosure, based on
// viewport width at first render - true (open) on desktop/tablet, false (collapsed) on phone.
// Deliberately NOT re-evaluated on resize/orientation change: this only sets where a section
// STARTS, the user's own click always wins after that, exactly like a real "defaultOpen" would
// if <details> had one (it doesn't - `open` isn't part of React's special controlled-form-value
// handling, which only covers input/textarea/select, so a plain, never-updated boolean prop
// behaves as an initial value in practice: React only touches the DOM's `open` attribute when
// this hook's return value itself changes between renders, which it never does here).
//
// Safe to read `window` directly in the initializer with no SSR/hydration-mismatch guard: this
// app has no server-rendered HTML to mismatch against (main.tsx does a plain client-side
// `createRoot(...).render(...)` into an empty <div id="root">), unlike EngagementTimeline.tsx's
// desktop/mobile SWAP (a genuinely different concern - picking between two different component
// trees - which stays a pure CSS media-query switch specifically to avoid any first-paint
// flicker; this hook only picks an initial disclosure state, so there's nothing to flicker).
const DESKTOP_BREAKPOINT = '(min-width: 641px)'

export function useDefaultOpen(): boolean {
  const [defaultOpen] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true
    return window.matchMedia(DESKTOP_BREAKPOINT).matches
  })
  return defaultOpen
}
