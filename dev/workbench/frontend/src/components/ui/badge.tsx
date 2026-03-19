import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const toneMap = {
  green: "bg-sage-100 text-sage-800",
  amber: "bg-amber-100 text-amber-800",
  blue: "bg-slate-200 text-slate-800",
  stone: "bg-stone-100 text-stone-700",
  rose: "bg-rose-100 text-rose-700",
} as const;

type Tone = keyof typeof toneMap;

export function Badge({
  className,
  tone = "stone",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm px-2.5 py-1 text-xs font-semibold tracking-wide",
        toneMap[tone],
        className
      )}
      {...props}
    />
  );
}
