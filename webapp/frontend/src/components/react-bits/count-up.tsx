import { useEffect, useRef, useState } from "react"
import { animate, useInView, useReducedMotion } from "motion/react"

// Adapted from React Bits "CountUp" (https://reactbits.dev) for our stack:
// motion/react drive + prefers-reduced-motion fallback (jumps to final value).

type CountUpProps = {
  to: number
  from?: number
  duration?: number
  decimals?: number
  prefix?: string
  suffix?: string
  className?: string
}

function format(value: number, decimals: number): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function CountUp({
  to,
  from = 0,
  duration = 1.1,
  decimals = 0,
  prefix = "",
  suffix = "",
  className,
}: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true, amount: 0.4 })
  const reduceMotion = useReducedMotion()
  const [display, setDisplay] = useState(reduceMotion ? to : from)

  useEffect(() => {
    if (!inView) {
      return
    }
    const target = Number.isFinite(to) ? to : 0
    const animationDuration = reduceMotion || !Number.isFinite(to) ? 0 : duration
    const controls = animate(from, target, {
      duration: animationDuration,
      ease: "easeOut",
      onUpdate: (value) => setDisplay(value),
    })
    return () => controls.stop()
  }, [inView, reduceMotion, to, from, duration])

  return (
    <span className={className} ref={ref}>
      {prefix}
      {format(display, decimals)}
      {suffix}
    </span>
  )
}
