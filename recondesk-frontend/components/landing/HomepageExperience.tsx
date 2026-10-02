"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, ArrowUpRight } from "lucide-react";

const sections = [
  ["modules", "GSTR modules"],
  ["engine", "Matching engine"],
  ["security", "Data security"],
  ["how-it-works", "Workflow"],
  ["pricing", "Pricing"],
  ["faq", "FAQs"],
] as const;

export function HomepageExperience() {
  const [active, setActive] = useState("");
  const [showTop, setShowTop] = useState(false);
  const progress = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let scheduled = 0;
    const update = () => {
      scheduled = 0;
      const total = document.documentElement.scrollHeight - window.innerHeight;
      if (progress.current) progress.current.style.transform = `scaleX(${total > 0 ? Math.min(1, Math.max(0, window.scrollY / total)) : 0})`;
      setShowTop(window.scrollY > 1400);
      let current = "";
      for (const [id] of sections) {
        const section = document.getElementById(id);
        if (section && section.getBoundingClientRect().top <= 210) current = id;
      }
      setActive(current);
    };
    const onScroll = () => { if (!scheduled) scheduled = requestAnimationFrame(update); };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    update();
    return () => { window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll); cancelAnimationFrame(scheduled); };
  }, []);
  useEffect(() => {
    // Animate only on arrival; no CSS hidden state, so content is always readable.
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const animations = new Set<Animation>();
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        if (preference.matches || typeof entry.target.animate !== "function") continue;
        const animation = entry.target.animate(
          [{ opacity: .55, transform: "translateY(18px)" }, { opacity: 1, transform: "translateY(0)" }],
          { duration: 650, easing: "cubic-bezier(.22,1,.36,1)" }
        );
        animations.add(animation);
        animation.onfinish = () => animations.delete(animation);
      }
    }, { threshold: .08 });
    document.querySelectorAll(".studio-product-stage, #modules > div > .grid > div, #engine > .grid > div, #security > .grid > div, #how-it-works > div, #pricing article, #blog > div").forEach((el) => observer.observe(el));
    const stop = () => { if (preference.matches) { animations.forEach((a) => a.cancel()); animations.clear(); } };
    preference.addEventListener("change", stop);
    return () => { observer.disconnect(); animations.forEach((a) => a.cancel()); preference.removeEventListener("change", stop); };
  }, []);
  return (
    <>
      <div className="studio-reading-progress" ref={progress} aria-hidden="true" />
      <nav className="studio-section-nav" aria-label="Homepage sections">
        <div className="studio-section-nav-inner"><span className="studio-section-label">EXPLORE THE DESK</span><div className="studio-section-links">{sections.map(([id, title]) => <a key={id} href={`#${id}`} aria-current={active === id ? "location" : undefined}>{title}</a>)}</div><a className="studio-section-cta" href="/auth/signup">Start free <ArrowUpRight size={14} /></a></div>
      </nav>
      {showTop && <a href="#main-content" className="studio-back-top" aria-label="Back to top"><ArrowUp size={17} /></a>}
    </>
  );
}
