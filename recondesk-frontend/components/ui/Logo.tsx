import React from "react";

interface LogoProps {
  className?: string;
  width?: number | string;
  height?: number | string;
}

export function Logo({ className = "", width = "auto", height = "1em" }: LogoProps) {
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 420 80"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      aria-label="ReconDesk"
      role="img"
    >
      <text
        x="0"
        y="60"
        fontFamily="'Plus Jakarta Sans', 'Helvetica Neue', Arial, sans-serif"
        fontWeight="700"
        fontSize="64px"
        fill="currentColor"
        letterSpacing="-1"
      >
        ReconDesk<tspan fill="#7B5CFA">•</tspan>
      </text>
    </svg>
  );
}
