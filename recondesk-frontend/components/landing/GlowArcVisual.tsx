import React from "react";

export function GlowArcVisual() {
  return (
    <div className="relative mx-auto -mb-24 flex w-full max-w-5xl items-center justify-center overflow-visible pointer-events-none select-none sm:-mb-36 md:-mb-44">
      {/* Outer ambient blur glow */}
      <div
        className="absolute -top-12 h-64 w-[90%] max-w-4xl rounded-full bg-[#F97316] opacity-35 blur-[90px] transition-all duration-700 sm:h-80 sm:opacity-40 sm:blur-[120px]"
        aria-hidden="true"
      />

      {/* Main Celestial Arc / Rising Planet Horizon */}
      <div className="relative flex h-48 w-full max-w-4xl items-end justify-center overflow-hidden sm:h-64 md:h-72">
        {/* The Arc Geometric Curvature */}
        <div
          className="relative h-[550px] w-[950px] rounded-[50%] transition-transform duration-700"
          style={{
            background: `
              radial-gradient(50% 50% at 50% 0%, 
                #FFF7ED 0%, 
                #FED7AA 12%, 
                #FB923C 30%, 
                #F97316 55%, 
                #EA580C 75%, 
                #9A3412 88%,
                #0A0A0A 100%
              )
            `,
            boxShadow: `
              0 -10px 40px 0 rgba(249, 115, 22, 0.45),
              0 -2px 10px 0 rgba(255, 255, 255, 0.8),
              0 30px 80px 20px rgba(10, 10, 10, 0.6)
            `,
          }}
        >
          {/* Inner highlight ring at the top border */}
          <div className="absolute inset-0 rounded-[50%] border-t-[1.5px] border-amber-100/90" />
          
          {/* Soft conic/radial light rays / sheen overlay */}
          <div
            className="absolute inset-0 rounded-[50%] opacity-40 mix-blend-overlay"
            style={{
              background: "conic-gradient(from 180deg at 50% 0%, transparent 0deg, #FFFFFF 90deg, transparent 180deg)",
            }}
          />
        </div>

        {/* Soft bottom vignette shadow to anchor the product panel */}
        <div className="absolute bottom-0 left-0 right-0 h-28 bg-gradient-to-t from-white via-white/40 to-transparent" />
      </div>
    </div>
  );
}
