// Port of scripts/dashboard.py's _fmt_duration()/_fmt() - kept as pure functions so both
// SessionsView and any future component can share them without re-deriving the rules.

export function formatDuration(seconds: number): string {
  if (seconds <= 0) return '-'
  const totalMinutes = Math.floor(seconds / 60)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours && minutes) return `${hours}h ${minutes}m`
  if (hours) return `${hours}h`
  if (minutes) return `${minutes}m`
  return '<1m'
}

export function formatNumber(n: number): string {
  return n.toLocaleString('en-US')
}

// List-price cost estimate (scripts/dashboard.py's _price_usage/_MODEL_PRICING_PER_MTOK).
// `partial` marks a total that's a floor, not the full figure - at least one contributing
// message came from a model absent from the pricing table (e.g. a synthetic/internal
// message, or a model shipped after the table was last refreshed) - rendered as a trailing
// "+" rather than silently understating spend.
export function formatCost(usd: number, partial?: boolean): string {
  const value = usd > 0 && usd < 0.01 ? usd.toFixed(4) : usd.toFixed(2)
  return `$${value}${partial ? '+' : ''}`
}
