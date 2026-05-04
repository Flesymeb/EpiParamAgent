import type { InputHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Input({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-11 w-full rounded-sm border border-sage-200 bg-white/70 px-4 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-sage-400 focus:ring-2 focus:ring-sage-200",
        className
      )}
      {...props}
    />
  );
}
