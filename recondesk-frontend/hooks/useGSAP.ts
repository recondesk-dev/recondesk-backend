"use client";

import { useEffect, useRef } from "react";
import { gsap } from "@/lib/gsap";

type GSAPCallback = (gsapInstance: typeof gsap) => void;

/**
 * useGSAP — creates a scoped GSAP context tied to a container element.
 * All animations registered in the callback are automatically reverted on unmount.
 *
 * @param callback  Setup function receiving the gsap instance.
 * @param deps      Dependency array (re-runs when deps change).
 * @param containerRef  Optional ref to scope the GSAP context.
 */
export function useGSAP(
  callback: GSAPCallback,
  deps: React.DependencyList = [],
  containerRef?: React.RefObject<HTMLElement | null>
) {
  const ctxRef = useRef<gsap.Context | null>(null);

  useEffect(() => {
    // Revert any previous context before creating a new one
    if (ctxRef.current) {
      ctxRef.current.revert();
    }

    const scope = containerRef?.current ?? undefined;
    ctxRef.current = gsap.context(() => {
      callback(gsap);
    }, scope);

    return () => {
      ctxRef.current?.revert();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return ctxRef;
}
