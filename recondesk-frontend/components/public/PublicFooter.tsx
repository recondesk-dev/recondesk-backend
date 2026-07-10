import Link from "next/link";
import { Logo } from "@/components/ui/Logo";

const DEFAULT_FIRM_GSTIN = "27ISKPK1273H1ZF";
const firmGstin = process.env.NEXT_PUBLIC_FIRM_GSTIN?.trim() || DEFAULT_FIRM_GSTIN;

type PublicFooterProps = {
  theme?: "dark" | "light" | "ledger";
};

export function PublicFooter({ theme = "dark" }: PublicFooterProps) {
  const isLight = theme === "light";
  const isLedger = theme === "ledger";
  const isPale = isLight || isLedger;

  return (
    <footer
      className={
        isLedger
          ? "border-t border-[#0B1D33] bg-[#0B1D33]"
          : isLight
            ? "border-t border-[#E8E8E8] bg-[#F5F5F5]"
            : "border-t border-white/10 bg-[#080a0e]"
      }
    >
      <div className={`mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 ${isPale ? "py-10 sm:py-12" : "py-12"}`}>
        <div
          className={`flex flex-col lg:flex-row lg:items-start lg:justify-between lg:gap-8 ${
            isPale ? "gap-8 sm:gap-10" : "gap-10"
          }`}
        >
          <div className={`max-w-sm ${isLight ? "max-sm:mx-auto max-sm:text-center" : ""}`}>
            <div
              className={`inline-flex items-baseline gap-0 font-bold tracking-tight ${
                isLedger ? "text-white" : isLight ? "text-[#0A0A0A]" : "text-white"
              }`}
            >
              <Logo width={210} height={40} />
            </div>
            <p
              className={`mt-3 text-sm ${
                isLedger ? "font-mono text-[12px] text-[#8A9AAB]" : isLight ? "text-[#6B6B6B]" : "text-slate-400"
              }`}
            >
              GST reconciliation built for CA firms.
            </p>
          </div>
          <div
            className={`flex flex-wrap gap-x-6 gap-y-2 text-sm ${
              isLedger
                ? "font-mono text-[12px] text-[#A8B5C4]"
                : isLight
                  ? "max-sm:justify-center max-sm:text-center text-[#3A3A3A]"
                  : "text-slate-400"
            }`}
          >
            <Link href="/privacy" className={isLedger ? "hover:text-white" : isLight ? "hover:text-[#0A0A0A]" : "hover:text-white"}>
              Privacy Policy
            </Link>
            <span className={`hidden sm:inline ${isLedger ? "text-[#3D4F63]" : isLight ? "text-[#E5E5E5]" : "text-white/20"}`} aria-hidden>
              |
            </span>
            <Link href="/terms" className={isLedger ? "hover:text-white" : isLight ? "hover:text-[#0A0A0A]" : "hover:text-white"}>
              Terms of Service
            </Link>
            <span className={`hidden sm:inline ${isLedger ? "text-[#3D4F63]" : isLight ? "text-[#E5E5E5]" : "text-white/20"}`} aria-hidden>
              |
            </span>
            <Link href="/refund" className={isLedger ? "hover:text-white" : isLight ? "hover:text-[#0A0A0A]" : "hover:text-white"}>
              Refund Policy
            </Link>
            <span className={`hidden sm:inline ${isLedger ? "text-[#3D4F63]" : isLight ? "text-[#E5E5E5]" : "text-white/20"}`} aria-hidden>
              |
            </span>
            <Link href="/contact" className={isLedger ? "hover:text-white" : isLight ? "hover:text-[#0A0A0A]" : "hover:text-white"}>
              Contact
            </Link>
          </div>
          <div
            className={`text-sm max-sm:text-center lg:text-right ${
              isLedger ? "font-mono text-[12px] text-[#8A9AAB]" : isLight ? "text-[#6B6B6B]" : "text-slate-500"
            }`}
          >
            <p>
              GSTIN:{" "}
              <span className={`font-mono ${isLedger ? "text-[#C5CDD6]" : isLight ? "text-[#3A3A3A]" : "text-slate-300"}`}>
                {firmGstin}
              </span>
            </p>
            <p className="mt-1">
              Phone:{" "}
              <a
                href="tel:+918605035248"
                className={`font-mono ${
                  isLedger
                    ? "text-[#C5CDD6] hover:text-white"
                    : isLight
                      ? "text-[#3A3A3A] hover:text-[#0A0A0A]"
                      : "text-slate-300 hover:text-white"
                }`}
              >
                +91 86050 35248
              </a>
            </p>
          </div>
        </div>
        <p
          className={`mt-10 border-t pt-8 text-center text-xs ${
            isLedger
              ? "border-[#1E3349] font-mono text-[#6B7C8F]"
              : isLight
                ? "border-[#E5E5E5] text-[#6B6B6B]"
                : "border-white/5 text-slate-500"
          }`}
        >
          © 2026 ReconDesk. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
