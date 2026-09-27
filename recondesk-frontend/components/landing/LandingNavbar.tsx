"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Logo } from "@/components/ui/Logo";
import { Menu, ShieldCheck, X } from "lucide-react";

export function LandingNavbar() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 10);
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const navLinks = [
    { label: "ReconDepth", href: "/depth", highlight: true },
    { label: "How It Works", href: "/#how-it-works" },
    { label: "Pricing", href: "/#pricing" },
    { label: "Blog", href: "/blog" },
  ];

  return (
    <header
      className={`sticky top-0 z-50 w-full transition-colors duration-200 border-b border-[#E5E5E2] ${
        scrolled
          ? "bg-white/90 backdrop-blur-md shadow-[0_2px_12px_rgba(0,0,0,0.03)]"
          : "bg-white/95 backdrop-blur-sm"
      }`}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Left: Official Brand Logo with purple dot */}
        <Link href="/" className="flex items-center gap-2 transition-opacity hover:opacity-90">
          <Logo height={34} />
        </Link>

        {/* Center: Functional Navigation Links */}
        <nav className="hidden items-center gap-7 md:flex">
          {navLinks.map((link) => (
            <Link
              key={link.label}
              href={link.href}
              className={`text-sm font-medium transition-colors duration-150 flex items-center gap-1.5 ${
                link.highlight
                  ? "font-bold text-[#7B5CFA] hover:text-[#6C4DE6]"
                  : "text-[#6B6B6B] hover:text-[#0A0A0A]"
              }`}
            >
              <span>{link.label}</span>
              {link.highlight && (
                <span className="rounded-full bg-purple-100 text-[#7B5CFA] text-[9px] font-extrabold px-1.5 py-0.2 border border-purple-200">
                  DEEP DIVE
                </span>
              )}
            </Link>
          ))}
        </nav>

        {/* Right: Security Trust + Sign In + Start Free CTA */}
        <div className="hidden items-center gap-5 md:flex">
          <Link
            href="/auth/login"
            className="text-sm font-medium text-[#6B6B6B] transition-colors hover:text-[#0A0A0A]"
          >
            Sign In
          </Link>

          <Link
            href="/auth/signup"
            className="inline-flex items-center justify-center gap-1.5 rounded-full bg-[#0A0A0A] px-5 py-2 text-sm font-semibold text-white transition-all hover:bg-[#262626] active:scale-[0.98]"
          >
            <span>Start Free</span>
            <span className="text-xs font-bold">→</span>
          </Link>
        </div>

        {/* Mobile Hamburger Toggle Button */}
        <div className="flex items-center gap-2 md:hidden">
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-[8px] border border-[#E5E5E2] text-[#0A0A0A] transition-colors hover:bg-[#F5F5F3]"
            aria-expanded={mobileMenuOpen}
            aria-label={mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
            onClick={() => setMobileMenuOpen((prev) => !prev)}
          >
            {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Menu Dropdown */}
      {mobileMenuOpen && (
        <div className="border-t border-[#E5E5E2] bg-white px-4 py-5 shadow-lg md:hidden">
          <div className="flex flex-col gap-3">
            {navLinks.map((link) => (
              <a
                key={link.label}
                href={link.href}
                className="rounded-[8px] px-3 py-2 text-sm font-medium text-[#6B6B6B] hover:bg-[#F5F5F3] hover:text-[#0A0A0A] transition-colors"
                onClick={() => setMobileMenuOpen(false)}
              >
                {link.label}
              </a>
            ))}
            <div className="pt-3 border-t border-[#E5E5E2] flex flex-col gap-2">
              <Link
                href="/auth/login"
                className="flex w-full items-center justify-center py-2 text-sm font-medium text-[#6B6B6B] hover:text-[#0A0A0A]"
                onClick={() => setMobileMenuOpen(false)}
              >
                Sign In
              </Link>
              <Link
                href="/auth/signup"
                className="flex w-full items-center justify-center gap-1.5 rounded-full bg-[#7B5CFA] py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#6C4DE6]"
                onClick={() => setMobileMenuOpen(false)}
              >
                <span>Start 60-Day Free Trial (2 GSTINs)</span>
                <span>→</span>
              </Link>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
