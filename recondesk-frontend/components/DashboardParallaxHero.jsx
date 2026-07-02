"use client";
import { useRef, useEffect } from "react";

export default function DashboardParallaxHero() {
  const wrapRef = useRef(null);
  const imgRef = useRef(null);
  const mouse = useRef({ x: 0, y: 0 });

  useEffect(() => {
    let raf;
    const start = performance.now();

    function tick(now) {
      const img = imgRef.current;
      if (img) {
        const t = (now - start) / 1000;
        const driftX = Math.sin(t / 6) * 10;
        const driftY = Math.cos(t / 8) * 8;
        const mouseX = mouse.current.x * 24;
        const mouseY = mouse.current.y * 24;
        const rotate = mouse.current.x * 1.5;
        img.style.transform = `translate(${driftX + mouseX}px, ${driftY + mouseY}px) rotate(${rotate}deg) scale(1.08)`;
      }
      raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  function handleMouseMove(e) {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const { left, top, width, height } = wrap.getBoundingClientRect();
    mouse.current.x = (e.clientX - left) / width - 0.5;
    mouse.current.y = (e.clientY - top) / height - 0.5;
  }

  function handleMouseLeave() {
    mouse.current.x = 0;
    mouse.current.y = 0;
  }

  return (
    <div
      ref={wrapRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{
        position: "relative",
        width: "100%",
        aspectRatio: "16 / 10",
        borderRadius: "20px",
        overflow: "hidden",
        boxShadow: "0 30px 60px -20px rgba(0,0,0,0.25)",
        background: "#f5f3ee",
      }}
    >
      <img
        ref={imgRef}
        src="/dashboard-hero.png"
        alt="ReconDesk dashboard showing GST reconciliation results"
        draggable={false}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: "top left",
          transform: "translate(0px, 0px) scale(1.08)",
          willChange: "transform",
          userSelect: "none",
          pointerEvents: "none",
        }}
      />
    </div>
  );
}
