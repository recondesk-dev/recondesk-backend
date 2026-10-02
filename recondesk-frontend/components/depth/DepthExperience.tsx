"use client";
import { createContext, useContext, useState, type ReactNode } from "react";
import { Pause, Play } from "lucide-react";
import "./depth-motion.css";
const MotionContext = createContext({ paused: false, toggle: () => {} });
export const useDepthMotion = () => useContext(MotionContext);
export function DepthExperience({ children }: { children: ReactNode }) {
  const [paused, setPaused] = useState(false);
  return <MotionContext.Provider value={{ paused, toggle: () => setPaused(value => !value) }}><div className="depth-experience min-h-screen font-sans" data-paused={paused}>{children}</div></MotionContext.Provider>;
}
export function DepthMotionToggle() {
  const { paused, toggle } = useDepthMotion();
  return <button type="button" className="depth-motion-toggle" onClick={toggle} aria-pressed={paused}>{paused ? <Play size={14} /> : <Pause size={14} />}{paused ? "Resume animations" : "Pause animations"}</button>;
}
