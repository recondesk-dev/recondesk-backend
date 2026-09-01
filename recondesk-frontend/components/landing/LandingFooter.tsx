import React from "react";
import Link from "next/link";

export function LandingFooter() {
  return (
    <footer className="border-t border-[#E5E5E2] bg-white py-12 text-sm text-[#6B6B6B]">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col items-center justify-between gap-6 sm:flex-row">
          {/* Logo + Copyright */}
          <div className="flex items-center gap-3">
            <div className="flex h-7 w-7 items-center justify-center rounded-[6px] bg-[#0A0A0A] text-white">
              <span className="text-xs font-bold">R</span>
            </div>
            <span className="font-semibold text-[#0A0A0A]">ReconDesk</span>
            <span className="text-xs text-[#6B6B6B]">
              © {new Date().getFullYear()} ReconDesk Inc. All rights reserved.
            </span>
          </div>

          {/* Quick links */}
          <div className="flex flex-wrap items-center gap-6 text-xs sm:text-sm font-medium">
            <Link href="/privacy" className="hover:text-[#0A0A0A] transition-colors">
              Privacy Policy
            </Link>
            <Link href="/terms" className="hover:text-[#0A0A0A] transition-colors">
              Terms of Service
            </Link>
            <Link href="/security" className="hover:text-[#0A0A0A] transition-colors">
              Security
            </Link>
            <a href="mailto:support@recondesk.com" className="hover:text-[#0A0A0A] transition-colors">
              Contact Support
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
