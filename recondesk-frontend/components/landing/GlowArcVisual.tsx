import React from "react";

export function GlowArcVisual() {
  return (
    <div className="absolute inset-0 -top-8 flex items-center justify-center overflow-visible pointer-events-none select-none">
      {/* Primary Soft Purple Ambient Halo */}
      <div
        className="h-80 w-[90%] max-w-4xl rounded-full bg-[#7B5CFA] opacity-20 blur-[110px] sm:h-96 sm:opacity-25 sm:blur-[140px]"
        aria-hidden="true"
      />

      {/* Secondary Soft Violet Core Sheen */}
      <div
        className="absolute top-8 h-56 w-[65%] max-w-2xl rounded-full bg-[#A78BFA] opacity-15 blur-[80px] sm:h-64 sm:opacity-20 sm:blur-[100px]"
        aria-hidden="true"
      />
    </div>
  );
}
