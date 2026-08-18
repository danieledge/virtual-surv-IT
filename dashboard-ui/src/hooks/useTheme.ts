import { useCallback, useEffect, useState } from 'react'

export type ThemeChoice = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'dashboard-theme'
const ORDER: ThemeChoice[] = ['system', 'light', 'dark']

function readStored(): ThemeChoice {
  if (typeof window === 'undefined') return 'system'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

function apply(choice: ThemeChoice) {
  if (typeof document === 'undefined') return
  if (choice === 'system') {
    delete document.documentElement.dataset.theme
  } else {
    document.documentElement.dataset.theme = choice
  }
}

// Manual light/dark override, independent of (but falling back to) the OS's
// prefers-color-scheme - see index.css's header comment for the CSS side of this (a
// `[data-theme]` attribute on <html>, guarding/duplicating the existing dark-token block).
// Persisted so the choice survives a reload; 'system' clears the override entirely rather than
// writing an explicit choice that happens to match the OS right now.
export function useTheme(): { theme: ThemeChoice; cycleTheme: () => void } {
  const [theme, setTheme] = useState<ThemeChoice>(() => readStored())

  useEffect(() => {
    apply(theme)
  }, [theme])

  const cycleTheme = useCallback(() => {
    setTheme((prev) => {
      const next = ORDER[(ORDER.indexOf(prev) + 1) % ORDER.length]!
      if (typeof window !== 'undefined') {
        if (next === 'system') window.localStorage.removeItem(STORAGE_KEY)
        else window.localStorage.setItem(STORAGE_KEY, next)
      }
      return next
    })
  }, [])

  return { theme, cycleTheme }
}
