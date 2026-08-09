// Per-CcEventType icon, backed by lucide-react (round 3 of the dashboard reskin) rather than
// the hand-rolled 16x16 SVGs this file used to contain - round 1 added lucide-react as a
// dependency specifically so this kind of hand-rolled icon set could be replaced with a real,
// consistent icon library. Split out from ccVisuals.ts (which stays plain data/functions)
// purely so this file can be all-components, keeping React Fast Refresh happy.

import {
  ArrowRightLeft,
  CheckCircle2,
  CircleX,
  GitFork,
  Repeat,
  RefreshCw,
  Rocket,
  Search,
  Siren,
  User,
  UserPlus,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import type { CcEventType } from '../../lib/commandCentre/types'

export interface EventTypeIconProps {
  type: CcEventType
  className?: string
}

/** One icon per event type, chosen for what the event actually represents rather than trying to
 * reproduce any reference mockup's own per-stage glyphs. Colored via `currentColor` wherever
 * this is used (EVENT_TYPE_META's tone mapping through `toneVar`, same as before), so a given
 * event type still reads as the same color on the pulse strip, the hero timeline blocks and the
 * detail badge. `retry` and `loop` intentionally use different icons (RefreshCw vs Repeat) even
 * though they share a tone, since a single retry and a full rework loop are different events. */
const EVENT_TYPE_ICON: Record<CcEventType, LucideIcon> = {
  started: Rocket,
  spawned: UserPlus,
  discovery: Search,
  handoff: ArrowRightLeft,
  escalation: Siren,
  tool_call: Wrench,
  error: CircleX,
  retry: RefreshCw,
  loop: Repeat,
  decision: GitFork,
  human: User,
  resolution: CheckCircle2,
}

export function EventTypeIcon({ type, className }: EventTypeIconProps) {
  const Icon = EVENT_TYPE_ICON[type] ?? Wrench
  return <Icon width={14} height={14} strokeWidth={1.75} className={className} aria-hidden="true" />
}
