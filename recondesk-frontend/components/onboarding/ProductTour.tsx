"use client";

import { useCallback, useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";
import { driver, type Driver } from "driver.js";
import "driver.js/dist/driver.css";

import { isApiError, onboardingTourApi } from "@/lib/api";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
  invalidateAuthProfileCache,
} from "@/lib/auth-profile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import {
  TOUR_STEPS,
  clearTourSession,
  nextPhase,
  readTourSession,
  stepIndex,
  writeTourSession,
  type TourPhase,
  type TourSession,
} from "@/lib/onboarding-tour";

const WAIT_MS = 12_000;
const POLL_MS = 120;

function waitForElement(selector: string, timeoutMs = WAIT_MS): Promise<Element | null> {
  return new Promise((resolve) => {
    const existing = document.querySelector(selector);
    if (existing) {
      resolve(existing);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => {
      const el = document.querySelector(selector);
      if (el) {
        window.clearInterval(timer);
        resolve(el);
        return;
      }
      if (Date.now() - started > timeoutMs) {
        window.clearInterval(timer);
        resolve(null);
      }
    }, POLL_MS);
  });
}

function pathBase(path: string): string {
  return path.split("?")[0] ?? path;
}

async function markTourComplete(token: string): Promise<void> {
  try {
    await onboardingTourApi.firstLoginComplete(token);
  } catch (e) {
    if (isApiError(e) && e.status === 404) return;
    console.warn("Failed to mark first-login complete", e);
  }
  await invalidateAuthProfileCache();
}

/**
 * Mount once inside the dashboard shell. Starts the tour when
 * ``is_first_login`` is true (or when Replay Demo Tour sets a force session).
 */
export function ProductTourController() {
  const token = useAccessToken();
  const router = useRouter();
  const pathname = usePathname();
  const driverRef = useRef<Driver | null>(null);
  const startingRef = useRef(false);
  const completedRef = useRef(false);

  const { data: profile } = useSWR(
    typeof token === "string" ? (["/api/v1/auth/me", token, "tour"] as const) : null,
    ([, t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );

  const destroyDriver = useCallback(() => {
    try {
      driverRef.current?.destroy();
    } catch {
      /* already destroyed */
    }
    driverRef.current = null;
  }, []);

  const finishTour = useCallback(
    async (tokenStr: string) => {
      if (completedRef.current) return;
      completedRef.current = true;
      clearTourSession();
      destroyDriver();
      await markTourComplete(tokenStr);
    },
    [destroyDriver]
  );

  const runPhase = useCallback(
    async (session: TourSession) => {
      const step = TOUR_STEPS.find((s) => s.phase === session.phase);
      if (!step || typeof token !== "string") return;

      const targetPath = step.path({
        clientId: session.clientId,
        runId: session.runId,
      });

      if (targetPath) {
        const here = typeof window !== "undefined" ? window.location.pathname + window.location.search : pathname;
        const hereBase = pathBase(here);
        const wantBase = pathBase(targetPath);
        if (hereBase !== wantBase) {
          writeTourSession(session);
          router.push(targetPath);
          return;
        }
        if (typeof window !== "undefined") {
          const want = new URL(targetPath, window.location.origin);
          if (want.search && want.search !== window.location.search) {
            writeTourSession(session);
            router.replace(targetPath);
            return;
          }
        }
      }

      const el = await waitForElement(step.element);
      if (!el) {
        const nxt = nextPhase(session.phase);
        if (!nxt) {
          await finishTour(token);
          return;
        }
        const nextSession = { ...session, phase: nxt };
        writeTourSession(nextSession);
        await runPhase(nextSession);
        return;
      }

      destroyDriver();
      completedRef.current = false;
      const idx = stepIndex(session.phase);

      const driverObj = driver({
        popoverClass: "recondesk-tour-popover",
        overlayColor: "rgba(17, 17, 17, 0.5)",
        stagePadding: 10,
        stageRadius: 16,
        animate: true,
        allowClose: true,
        smoothScroll: true,
        showProgress: false,
        nextBtnText: session.phase === "export" ? "Done" : "Next",
        prevBtnText: "Back",
        doneBtnText: "Done",
        onDestroyed: () => {
          if (!completedRef.current) {
            void finishTour(token);
          }
        },
        steps: [
          {
            element: step.element,
            popover: {
              title: step.title,
              description: `${step.description}<div class="recondesk-tour-progress">${idx + 1} of ${TOUR_STEPS.length}</div>`,
              side: "bottom",
              align: "start",
              onNextClick: () => {
                const nxt = nextPhase(session.phase);
                if (!nxt) {
                  completedRef.current = true;
                  clearTourSession();
                  destroyDriver();
                  void markTourComplete(token);
                  return;
                }
                const nextSession: TourSession = { ...session, phase: nxt };
                writeTourSession(nextSession);
                destroyDriver();
                void runPhase(nextSession);
              },
              onPrevClick: () => {
                const i = stepIndex(session.phase);
                if (i <= 0) return;
                const prevPhase = TOUR_STEPS[i - 1]?.phase as TourPhase;
                const prevSession: TourSession = { ...session, phase: prevPhase };
                writeTourSession(prevSession);
                destroyDriver();
                void runPhase(prevSession);
              },
            },
          },
        ],
      });

      driverRef.current = driverObj;
      driverObj.drive();
    },
    [destroyDriver, finishTour, pathname, router, token]
  );

  const bootstrap = useCallback(async () => {
    if (typeof token !== "string" || startingRef.current) return;

    const existing = readTourSession();
    if (existing) {
      startingRef.current = true;
      try {
        await runPhase(existing);
      } finally {
        startingRef.current = false;
      }
      return;
    }

    if (!profile) return;
    // Only auto-start when explicitly true (Replay uses sessionStorage instead).
    if (profile.is_first_login !== true) return;
    if (profile.onboarding_completed === false) return;

    startingRef.current = true;
    try {
      const demo = await onboardingTourApi.ensureDemo(token);
      if (!demo.client_id || !demo.run_id) {
        console.warn("Demo seed returned without run_id; tour deferred");
        return;
      }
      const session: TourSession = {
        phase: "sidebar",
        clientId: demo.client_id,
        runId: demo.run_id,
        force: false,
      };
      writeTourSession(session);
      void mutate((key) => Array.isArray(key) && String(key[0]).startsWith("dw"));
      await runPhase(session);
    } catch (e) {
      console.warn("Could not start product tour", e);
    } finally {
      startingRef.current = false;
    }
  }, [profile, runPhase, token]);

  useEffect(() => {
    void bootstrap();
    return () => {
      destroyDriver();
    };
  }, [bootstrap, destroyDriver, pathname]);

  return null;
}

/** Start (or restart) the tour from the Help menu — ignores is_first_login. */
export async function replayProductTour(token: string): Promise<void> {
  const demo = await onboardingTourApi.ensureDemo(token);
  if (!demo.client_id || !demo.run_id) {
    throw new Error("Demo client is not ready yet. Try again in a moment.");
  }
  writeTourSession({
    phase: "sidebar",
    clientId: demo.client_id,
    runId: demo.run_id,
    force: true,
  });
  window.location.assign("/dashboard");
}
