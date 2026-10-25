import { cn } from "@/lib/utils";
import type { ImgHTMLAttributes } from "react";

interface BotoizeLogoProps extends ImgHTMLAttributes<HTMLImageElement> {
  className?: string;
}

/**
 * Botoize brand mark for in-app surfaces.
 *
 * Uses the user-provided avaiak artwork, shared with the favicon.
 */
export function BotoizeLogo({ className, ...props }: BotoizeLogoProps) {
  return (
    <img
      src="/botoize.png"
      alt=""
      className={cn("block object-contain", className)}
      aria-hidden="true"
      {...props}
    />
  );
}
