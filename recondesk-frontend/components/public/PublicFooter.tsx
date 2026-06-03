import Link from "next/link";

const DEFAULT_FIRM_GSTIN = "27ISKPK1273H1ZF";
const firmGstin = process.env.NEXT_PUBLIC_FIRM_GSTIN?.trim() || DEFAULT_FIRM_GSTIN;

type PublicFooterProps = {
  theme?: "dark" | "light";
};

export function PublicFooter({ theme = "dark" }: PublicFooterProps) {
  const isLight = theme === "light";

  return (
    <footer className={isLight ? "border-t border-[#E8E8E8] bg-[#F5F5F5]" : "border-t border-white/10 bg-[#080a0e]"}>
      <div className={`mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 ${isLight ? "py-10 sm:py-12" : "py-12"}`}>
        <div
          className={`flex flex-col lg:flex-row lg:items-start lg:justify-between lg:gap-8 ${
            isLight ? "gap-8 sm:gap-10" : "gap-10"
          }`}
        >
          <div className={`max-w-sm ${isLight ? "max-sm:mx-auto max-sm:text-center" : ""}`}>
            <div
              className={`inline-flex items-baseline gap-0 font-bold tracking-tight ${
                isLight ? "text-[#0A0A0A]" : "text-white"
              }`}
            >
              <span className="text-2xl sm:text-3xl">ReconDesk</span>
              <span className="-ml-1.5 text-2xl leading-none text-purple-600 sm:ml-0 sm:text-3xl" aria-hidden="true">
                •
              </span>
            </div>
            <p className={`mt-3 text-sm ${isLight ? "text-[#6B6B6B]" : "text-slate-400"}`}>
              GST reconciliation built for CA firms.
            </p>
          </div>
          <div
            className={`flex flex-wrap gap-x-6 gap-y-2 text-sm ${
              isLight ? "max-sm:justify-center max-sm:text-center text-[#3A3A3A]" : "text-slate-400"
            }`}
          >
            <Link href="/privacy" className={isLight ? "hover:text-[#0A0A0A]" : "hover:text-white"}>
              Privacy Policy
            </Link>
            <span className={`hidden sm:inline ${isLight ? "text-[#E5E5E5]" : "text-white/20"}`} aria-hidden>
              |
            </span>
            <Link href="/terms" className={isLight ? "hover:text-[#0A0A0A]" : "hover:text-white"}>
              Terms of Service
            </Link>
            <span className={`hidden sm:inline ${isLight ? "text-[#E5E5E5]" : "text-white/20"}`} aria-hidden>
              |
            </span>
            <Link href="/refund" className={isLight ? "hover:text-[#0A0A0A]" : "hover:text-white"}>
              Refund Policy
            </Link>
            <span className={`hidden sm:inline ${isLight ? "text-[#E5E5E5]" : "text-white/20"}`} aria-hidden>
              |
            </span>
            <a href="mailto:contact@recondesk.in" className={isLight ? "hover:text-[#0A0A0A]" : "hover:text-white"}>
              Contact
            </a>
          </div>
          <p
            className={`text-sm max-sm:text-center lg:text-right ${isLight ? "text-[#6B6B6B]" : "text-slate-500"}`}
          >
            GSTIN:{" "}
            <span className={`font-mono ${isLight ? "text-[#3A3A3A]" : "text-slate-300"}`}>{firmGstin}</span>
          </p>
        </div>
        <p
          className={`mt-10 border-t pt-8 text-center text-xs ${
            isLight ? "border-[#E5E5E5] text-[#6B6B6B]" : "border-white/5 text-slate-500"
          }`}
        >
          © 2026 ReconDesk. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
