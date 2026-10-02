"use client";
import { useEffect, useRef, useState } from "react";

/** A slow content clock; CSS handles the frames. Sleeps offscreen and in background tabs. */
export function useAutoplay(count: number, paused = false, duration = 5200) {
  const ref = useRef<HTMLDivElement>(null);
  const [step, setStep] = useState(0);
  const [visible, setVisible] = useState(false);
  const [foreground, setForeground] = useState(true);
  const [reduced, setReduced] = useState(true);
  const [interacting, setInteracting] = useState(false);
  useEffect(() => {
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(media.matches);
    const visibility = () => setForeground(!document.hidden);
    sync(); visibility();
    media.addEventListener("change", sync);
    document.addEventListener("visibilitychange", visibility);
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { threshold: .15 });
    if (ref.current) observer.observe(ref.current);
    return () => { observer.disconnect(); media.removeEventListener("change", sync); document.removeEventListener("visibilitychange", visibility); };
  }, []);
  const running = visible && foreground && !reduced && !paused && !interacting;
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setStep(value => (value + 1) % count), duration);
    return () => clearInterval(timer);
  }, [running, count, duration, step]);
  return { ref, step, setStep, running, reduced, setInteracting };
}
