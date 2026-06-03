import Link from "next/link";

const DEFAULT_FIRM_GSTIN = "27ISKPK1273H1ZF";
const firmGstin = process.env.NEXT_PUBLIC_FIRM_GSTIN?.trim() || DEFAULT_FIRM_GSTIN;

export function PublicFooter() {
  return (
    <footer className="border-t border-white/10 bg-[#080a0e]">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-10 lg:flex-row lg:items-start lg:justify-between lg:gap-8">
          <div className="max-w-sm">
            <div className="inline-flex items-baseline gap-0 text-xl font-bold tracking-tight text-white sm:text-2xl">
              <span>ReconDesk</span>
              <span className="text-xl leading-none text-purple-600 sm:text-2xl" aria-hidden="true">
                •
              </span>
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
