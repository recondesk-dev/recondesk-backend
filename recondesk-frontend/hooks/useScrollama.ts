"use client";

import { useEffect, useRef, useState } from "react";

interface ScrollamaConfig {
  offset?: number; // 0–1, fraction of viewport where trigger fires
  debug?: boolean;
  once?: boolean;
}

interface StepProgress {
  index: number;
  progress: number; // 0–1 within current step
  direction: "up" | "down";
}

// Minimal local typing for the scrollama instance — avoids needing @types/scrollama
interface ScrollamaInstance {
  setup(opts: {
    step: HTMLElement[];
    offset?: number;
    debug?: boolean;
    progress?: boolean;
    once?: boolean;
  }): ScrollamaInstance;
  onStepEnter(fn: (resp: { index: number; direction: string }) => void): ScrollamaInstance;
  onStepProgress(fn: (resp: { index: number; progress: number; direction: string }) => void): ScrollamaInstance;
  onStepExit(fn: (resp: { index: number; direction: string }) => void): ScrollamaInstance;
  resize(): void;
  destroy(): void;
}

/**
 * useScrollama — wraps the Scrollama library with a React-friendly API.
 *
 * @param stepsRef   Ref pointing to the container whose children are steps.
 * @param config     Scrollama configuration options.
 * @returns          { currentStep, stepProgress } for driving animations.
 */
export function useScrollama(
  stepsRef: React.RefObject<HTMLElement | null>,
  config: ScrollamaConfig = {}
) {
  const [currentStep, setCurrentStep] = useState<number>(-1);
  const [stepProgress, setStepProgress] = useState<StepProgress>({
    index: -1,
    progress: 0,
    direction: "down",
  });
  const scrollerRef = useRef<ScrollamaInstance | null>(null);

  useEffect(() => {
    if (!stepsRef.current) return;
    const container = stepsRef.current;

    import("scrollama").then((mod) => {
      // Scrollama exports a factory function as default
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const scrollamaFactory = (mod.default ?? mod) as unknown as () => ScrollamaInstance;
      const scroller = scrollamaFactory();
      scrollerRef.current = scroller;

      const steps = Array.from(container.children) as HTMLElement[];

      scroller
        .setup({ step: steps, offset: config.offset ?? 0.5, debug: config.debug ?? false, progress: true, once: config.once ?? false })
        .onStepEnter((resp) => {
          setCurrentStep(resp.index);
        })
        .onStepProgress((resp) => {
          setStepProgress({
            index: resp.index,
            progress: resp.progress,
            direction: resp.direction as "up" | "down",
          });
        })
        .onStepExit(() => {
          // intentional no-op: keep last known state
        });

      const handleResize = () => scroller.resize();
      window.addEventListener("resize", handleResize);

      // Cleanup inside the async block
      return () => {
        window.removeEventListener("resize", handleResize);
      };
    });

    return () => {
      scrollerRef.current?.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { currentStep, stepProgress };
}
