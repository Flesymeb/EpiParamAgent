import { useRef } from "react"
import type { CSSProperties, MouseEvent, ReactNode } from "react"

import { cn } from "@/lib/utils"

// Adapted from React Bits "SpotlightCard" (https://reactbits.dev): a radial
// highlight follows the cursor over the card. Pure CSS variables — no deps.

type SpotlightCardProps = {
  children: ReactNode
  className?: string
  spotlightColor?: string
}

export function SpotlightCard({
  children,
  className,
  spotlightColor = "rgba(56, 189, 248, 0.15)",
}: SpotlightCardProps) {
  const ref = useRef<HTMLDivElement>(null)

  function handleMouseMove(event: MouseEvent<HTMLDivElement>) {
    const element = ref.current
    if (!element) {
      return
    }
    const rect = element.getBoundingClientRect()
    element.style.setProperty("--spotlight-x", `${event.clientX - rect.left}px`)
    element.style.setProperty("--spotlight-y", `${event.clientY - rect.top}px`)
  }

  return (
    <div
      className={cn("group relative overflow-hidden", className)}
      onMouseMove={handleMouseMove}
      ref={ref}
      style={{ "--spotlight-color": spotlightColor } as CSSProperties}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-10 opacity-0 mix-blend-plus-lighter transition-opacity duration-500 motion-reduce:transition-none group-hover:opacity-100"
        style={{
          background:
            "radial-gradient(340px circle at var(--spotlight-x, 50%) var(--spotlight-y, 0px), var(--spotlight-color), transparent 70%)",
        }}
      />
      {children}
    </div>
  )
}
