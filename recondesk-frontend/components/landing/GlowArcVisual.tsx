import React from "react";

export function GlowArcVisual() {
  return (
    <div className="relative mx-auto -mb-28 flex w-full max-w-5xl items-center justify-center overflow-visible pointer-events-none select-none sm:-mb-36 md:-mb-40">
      {/* Primary Soft Purple Ambient Halo */}
      <div
        className="absolute -top-16 h-72 w-[85%] max-w-3xl rounded-full bg-[#7B5CFA] opacity-25 blur-[100px] transition-all duration-700 sm:h-80 sm:opacity-30 sm:blur-[130px]"
        aria-hidden="true"
      />

      {/* Secondary Soft Violet Core Sheen */}
      <div
        className="absolute -top-8 h-48 w-[60%] max-w-xl rounded-full bg-[#A78BFA] opacity-20 blur-[80px] transition-all duration-700 sm:h-56 sm:opacity-25 sm:blur-[100px]"
        aria-hidden="true"
      />
    </div>
  );
}
