import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Button({
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-sm bg-sage-700 px-4 py-2.5 text-sm font-semibold text-white transition duration-200 hover:bg-sage-800 disabled:cursor-not-allowed disabled:opacity-60",
        className
      )}
      {...props}
    />
  );
}
