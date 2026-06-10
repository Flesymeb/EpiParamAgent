import { useMemo } from "react"
import { motion, useReducedMotion } from "motion/react"

import { cn } from "@/lib/utils"

// Adapted from React Bits "BlurText" (https://reactbits.dev): words fade in and
// unblur with a slight upward drift, staggered. One-shot entrance (not looped),
// so it stays tasteful on a research tool. Falls back to plain text when the
// user prefers reduced motion.

type BlurTextProps = {
  text: string
  className?: string
  /** Per-word stagger in seconds. */
  delayStep?: number
}

export function BlurText({ text, className, delayStep = 0.07 }: BlurTextProps) {
  const reduceMotion = useReducedMotion()
  const words = useMemo(() => text.split(" "), [text])

  if (reduceMotion) {
    return <span className={className}>{text}</span>
  }

  return (
    <span className={cn("inline-flex flex-wrap", className)}>
      {words.map((word, index) => (
        <motion.span
          animate={{ opacity: 1, filter: "blur(0px)", y: 0 }}
          className="mr-[0.25em] inline-block"
          initial={{ opacity: 0, filter: "blur(8px)", y: "0.35em" }}
          key={`${word}-${index}`}
          transition={{
            delay: index * delayStep,
            duration: 0.45,
            ease: "easeOut",
          }}
        >
          {word}
        </motion.span>
      ))}
    </span>
  )
}
