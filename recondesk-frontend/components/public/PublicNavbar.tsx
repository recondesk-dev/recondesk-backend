"use client";

import { useState } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";

type PublicNavbarProps = {
  theme?: "dark" | "light";
};

export function PublicNavbar({ theme = "dark" }: PublicNavbarProps) {
  const isLight = theme === "light";
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const linkClass = isLight
    ? "text-sm font-medium text-[#3A3A3A] transition hover:text-[#0A0A0A]"
    : "text-sm font-medium text-slate-300 transition hover:text-white";

  const mobileLinkClass = isLight
    ? "block rounded-lg px-3 py-3 text-base font-medium text-[#3A3A3A] transition hover:bg-[#F5F5F5] hover:text-[#0A0A0A]"
    : "block rounded-lg px-3 py-3 text-base font-medium text-slate-300 transition hover:bg-white/5 hover:text-white";

  return (
    <header
      className={
        isLight
          ? "sticky top-0 z-50 border-b border-[#E5E5E5] bg-white"
          : "sticky top-0 z-50 border-b border-white/10 bg-[#0a0c10]/85 backdrop-blur-md"
      }
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className={`font-brand inline-flex shrink-0 items-baseline gap-0 font-bold tracking-tight ${
            isLight ? "text-[#0A0A0A]" : "text-white"
          }`}
          onClick={() => setMobileMenuOpen(false)}
        >
          <span className={isLight ? "text-xl sm:text-3xl" : "text-2xl sm:text-3xl"}>ReconDesk</span>
          <span
            className={`-ml-1.5 leading-none text-purple-600 sm:ml-0 ${
              isLight ? "text-xl sm:text-3xl" : "text-2xl sm:text-3xl"
            }`}
            aria-hidden="true"
          >
            •
          </span>
        </Link>

        {isLight ? (
          <>
            <nav className="hidden items-center gap-6 sm:flex">
              <Link href="/pricing" className={linkClass}>
                Pricing
              </Link>
              <Link href="/auth/login" className={linkClass}>
                Login
              </Link>
              <Link
                href="/auth/signup"
                className="inline-flex min-h-[40px] items-center justify-center rounded-lg bg-[var(--accent)] px-4 text-sm font-semibold text-white shadow-sm transition hover:opacity-95"
              >
                Start Free
              </Link>
            </nav>

            <button
              type="button"
              className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg border border-[#E5E5E5] text-[#0A0A0A] sm:hidden"
              aria-expanded={mobileMenuOpen}
              aria-controls="landing-mobile-nav"
              aria-label={mobileMenuOpen ? "Close menu" : "Open menu"}
              onClick={() => setMobileMenuOpen((open) => !open)}
            >
              {mobileMenuOpen ? <X className="h-5 w-5" aria-hidden /> : <Menu className="h-5 w-5" aria-hidden />}
            </button>
          </>
        ) : (
          <nav className="flex items-center gap-3 sm:gap-6">
            <Link href="/pricing" className={linkClass}>
              Pricing
            </Link>
            <Link href="/auth/login" className={linkClass}>
              Login
            </Link>
            <Link
              href="/auth/signup"
              className="inline-flex min-h-[40px] items-center justify-center rounded-lg bg-[var(--accent)] px-4 text-sm font-semibold text-white shadow-sm transition hover:opacity-95"
            >
              Start Free
            </Link>
          </nav>
        )}
      </div>

      {isLight && mobileMenuOpen ? (
        <nav
          id="landing-mobile-nav"
          className="border-t border-[#E5E5E5] px-4 py-3 sm:hidden"
        >
          <div className="flex flex-col gap-1">
            <Link href="/pricing" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>
              Pricing
            </Link>
            <Link href="/auth/login" className={mobileLinkClass} onClick={() => setMobileMenuOpen(false)}>
              Login
            </Link>
            <Link
              href="/auth/signup"
              className="mt-2 inline-flex min-h-[44px] items-center justify-center rounded-lg bg-[var(--accent)] px-4 text-sm font-semibold text-white transition hover:opacity-95"
              onClick={() => setMobileMenuOpen(false)}
            >
              Start Free
            </Link>
          </div>
        </nav>
      ) : null}
    </header>
  );
}
