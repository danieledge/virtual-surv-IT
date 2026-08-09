// Tiny classname joiner - avoids pulling in `clsx`/`tailwind-merge` for what these small
// primitives need. Falsy values (false/null/undefined/'') are dropped.
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(' ')
}
