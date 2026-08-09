import type { ButtonHTMLAttributes } from 'react'
import { cn } from './cn'

export type ButtonVariant = 'primary' | 'ghost'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: 'btn-primary',
  ghost: 'btn-ghost',
}

/**
 * Not a replacement for `.link-btn` (the existing inline cross-tab nav links in
 * index.css) - that pattern stays as-is. This is for a real button affordance where round 2/3
 * needs one (e.g. Command Centre replay controls).
 */
export function Button({ variant = 'primary', className, children, ...rest }: ButtonProps) {
  return (
    <button className={cn(VARIANT_CLASS[variant], className)} {...rest}>
      {children}
    </button>
  )
}
