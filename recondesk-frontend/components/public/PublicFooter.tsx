import Link from "next/link";

function LogoMark() {
  return (
    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--accent)]">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="text-white" aria-hidden>
        <path
          d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 1-2-2V9m0 0h18"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

const DEFAULT_FIRM_GSTIN = "27ISKPK1273H1ZF";
const firmGstin = process.env.NEXT_PUBLIC_FIRM_GSTIN?.trim() || DEFAULT_FIRM_GSTIN;

export function PublicFooter() {
  return (
    <footer className="border-t border-white/10 bg-[#080a0e]">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-10 lg:flex-row lg:items-start lg:justify-between lg:gap-8">
          <div className="max-w-sm">
            <div className="flex items-center gap-2.5 text-white">
              <LogoMark />
              <span className="font-brand text-sm font-bold tracking-[0.2em]">RECONDESK</span>
            </div>
            <p className="mt-3 text-sm text-slate-400">GST reconciliation built for CA firms.</p>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-slate-400">
            <Link href="/privacy" className="hover:text-white">
              Privacy Policy
            </Link>
            <span className="hidden text-white/20 sm:inline" aria-hidden>
              |
            </span>
            <Link href="/terms" className="hover:text-white">
              Terms of Service
            </Link>
            <span className="hidden text-white/20 sm:inline" aria-hidden>
              |
            </span>
            <Link href="/refund" className="hover:text-white">
              Refund Policy
            </Link>
            <span className="hidden text-white/20 sm:inline" aria-hidden>
              |
            </span>
            <a href="mailto:contact@recondesk.in" className="hover:text-white">
              Contact
            </a>
          </div>
          <p className="text-sm text-slate-500 lg:text-right">
            GSTIN:{" "}
            <span className="font-mono text-slate-300">{firmGstin}</span>
          </p>
        </div>
        <p className="mt-10 border-t border-white/5 pt-8 text-center text-xs text-slate-500">
          © 2026 ReconDesk. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
