/**
 * First-login product tour (driver.js) — step config + session resume helpers.
 *
 * Multi-page flow stores the next phase in sessionStorage so navigation can
 * continue the tour after the previous page unmounts.
 */

export const TOUR_STORAGE_KEY = "recondesk_product_tour";
export const TOUR_FORCE_KEY = "recondesk_product_tour_force";

export type TourPhase =
  | "sidebar"
  | "demo-client"
  | "pr-import"
  | "gstr-autofetch"
  | "results-itc"
  | "finalize"
  | "export";

export type TourSession = {
  phase: TourPhase;
  clientId: string;
  runId: string;
  /** When true, ignore is_first_login (Replay Demo Tour). */
  force: boolean;
};

export const TOUR_PHASES: TourPhase[] = [
  "sidebar",
  "demo-client",
  "pr-import",
  "gstr-autofetch",
  "results-itc",
  "finalize",
  "export",
];

export type TourStepDef = {
  phase: TourPhase;
  element: string;
  title: string;
  description: string;
  /** Path to ensure before highlighting (null = stay on current page). */
  path: (ctx: { clientId: string; runId: string }) => string | null;
};

export const TOUR_STEPS: TourStepDef[] = [
  {
    phase: "sidebar",
    element: '[data-tour="sidebar-nav"]',
    title: "Your workspace",
    description:
      "Navigate Clients, Reconciliations, Vendors, and Settings from this sidebar. Everything for your firm lives here.",
    path: () => "/dashboard",
  },
  {
    phase: "demo-client",
    element: '[data-tour="demo-client-card"]',
    title: "Demo client — ready to explore",
    description:
      "We pre-loaded “Demo Client - Sample Reconciliation” with sample invoices and ran reconciliation so you can explore live Decision Layer results.",
    path: () => "/dashboard",
  },
  {
    phase: "pr-import",
    element: '[data-tour="purchase-register-import"]',
    title: "Purchase Register import",
    description:
      "Here’s where you’d upload your real client’s purchase register (Tally, Busy, or any Excel). Column mapping is auto-detected.",
    path: ({ clientId }) =>
      `/reconcile/${clientId}/new?tour=1&tourStep=pr`,
  },
  {
    phase: "gstr-autofetch",
    element: '[data-tour="gstr2b-autofetch"]',
    title: "GSTR-2B auto-fetch",
    description:
      "Connect GSTN once, then fetch GSTR-2B with an OTP via Sandbox — no manual portal downloads for every client.",
    path: ({ clientId }) =>
      `/reconcile/${clientId}/new?tour=1&tourStep=gstr`,
  },
  {
    phase: "results-itc",
    element: '[data-tour="missed-itc-row"]',
    title: "Decision Layer: WHAT / WHY / NEXT",
    description:
      "This MISSED_ITC row is in GSTR-2B but missing from books. Every issue shows WHAT happened, WHY it matters, and NEXT action for the CA.",
    path: ({ runId }) =>
      `/reconcile/runs/${runId}/results?tour=1&tab=itc`,
  },
  {
    phase: "finalize",
    element: '[data-tour="finalize-button"]',
    title: "Finalize (admin-only lock)",
    description:
      "When review is done, Finalize locks the run. Only the CA principal (admin) can finalize — staff can prepare, not lock.",
    path: ({ runId }) =>
      `/reconcile/runs/${runId}/results?tour=1&tab=itc`,
  },
  {
    phase: "export",
    element: '[data-tour="export-button"]',
    title: "Export filtered reports",
    description:
      "Export filtered Excel or PDF reports for the client file — status filters, ITC eligibility, and period scoping included.",
    path: ({ runId }) =>
      `/reconcile/runs/${runId}/results?tour=1&tab=itc`,
  },
];

export function readTourSession(): TourSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(TOUR_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as TourSession;
    if (!parsed?.phase || !parsed?.clientId || !parsed?.runId) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeTourSession(session: TourSession): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(TOUR_STORAGE_KEY, JSON.stringify(session));
}

export function clearTourSession(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(TOUR_STORAGE_KEY);
  sessionStorage.removeItem(TOUR_FORCE_KEY);
}

export function nextPhase(phase: TourPhase): TourPhase | null {
  const i = TOUR_PHASES.indexOf(phase);
  if (i < 0 || i >= TOUR_PHASES.length - 1) return null;
  return TOUR_PHASES[i + 1]!;
}

export function stepIndex(phase: TourPhase): number {
  return Math.max(0, TOUR_PHASES.indexOf(phase));
}
