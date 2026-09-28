import React from "react";
import Link from "next/link";
import { Logo } from "@/components/ui/Logo";
import { ShieldCheck } from "lucide-react";

export function LandingFooter() {
  return (
    <footer className="border-t border-[#CBD5E1]/60 bg-[#DDE2EE] pt-16 pb-12 text-sm text-[#5B6577]">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-2 gap-8 md:grid-cols-5 lg:gap-12">
          {/* Brand Col */}
          <div className="col-span-2 space-y-4">
            <Link href="/" className="inline-flex items-center gap-2">
              <Logo height={28} />
            </Link>
            <p className="max-w-sm text-xs leading-relaxed text-[#6B6B6B]">
              The intelligent GST reconciliation decision engine built specifically for Chartered Accountants and tax professionals in India.
            </p>
            <div className="flex items-center gap-2 text-xs text-[#0A0A0A] font-medium">
              <ShieldCheck className="h-4 w-4 text-emerald-600" />
              <span>SOC-2 Certified Infrastructure • AES-256</span>
            </div>
          </div>

          {/* Product Links */}
          <div className="space-y-3">
            <p className="text-xs font-bold uppercase tracking-wider text-[#0A0A0A]">ReconDesk Engine</p>
            <ul className="space-y-2 text-xs">
              <li>
                <Link href="/depth" className="font-bold text-[#7B5CFA] hover:text-[#6C4DE6] transition-colors flex items-center gap-1">
                  <span>ReconDepth Specs</span>
                  <span className="text-[9px] bg-purple-100 text-[#7B5CFA] px-1.5 py-0.2 rounded font-extrabold">NEW</span>
                </Link>
              </li>
              <li>
                <a href="/#modules" className="hover:text-[#0A0A0A] transition-colors">
                  GSTR-2B ↔ PR (ITC)
                </a>
              </li>
              <li>
                <a href="/#modules" className="hover:text-[#0A0A0A] transition-colors">
                  GSTR-1 ↔ Sales
                </a>
              </li>
              <li>
                <a href="/#modules" className="hover:text-[#0A0A0A] transition-colors">
                  GSTR-3B Notice Shield
                </a>
              </li>
              <li>
                <a href="/#modules" className="hover:text-[#0A0A0A] transition-colors">
                  GSTR-9C Workpapers
                </a>
              </li>
            </ul>
          </div>

          {/* Resources & Support */}
          <div className="space-y-3">
            <p className="text-xs font-bold uppercase tracking-wider text-[#0A0A0A]">Quick Links</p>
            <ul className="space-y-2 text-xs">
              <li>
                <a href="/#how-it-works" className="hover:text-[#0A0A0A] transition-colors">
                  How It Works
                </a>
              </li>
              <li>
                <a href="/#pricing" className="hover:text-[#0A0A0A] transition-colors">
                  Pricing Plans
                </a>
              </li>
              <li>
                <Link href="/blog" className="hover:text-[#0A0A0A] transition-colors">
                  Blog &amp; Insights
                </Link>
              </li>
              <li>
                <a href="/#faq" className="hover:text-[#0A0A0A] transition-colors">
                  FAQ
                </a>
              </li>
              <li>
                <Link href="/auth/login" className="hover:text-[#0A0A0A] transition-colors">
                  Sign In
                </Link>
              </li>
              <li>
                <Link href="/auth/signup" className="hover:text-[#0A0A0A] transition-colors">
                  Start Free Trial
                </Link>
              </li>
            </ul>
          </div>

          {/* Legal */}
          <div className="space-y-3">
            <p className="text-xs font-bold uppercase tracking-wider text-[#0A0A0A]">Legal &amp; Trust</p>
            <ul className="space-y-2 text-xs">
              <li>
                <Link href="/privacy" className="hover:text-[#0A0A0A] transition-colors">
                  Privacy Policy
                </Link>
              </li>
              <li>
                <Link href="/terms" className="hover:text-[#0A0A0A] transition-colors">
                  Terms of Service
                </Link>
              </li>
              <li>
                <Link href="/security" className="hover:text-[#0A0A0A] transition-colors">
                  Security Guarantee
                </Link>
              </li>
            </ul>
          </div>
        </div>

        {/* Bottom Bar */}
        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-[#E5E5E2] pt-8 text-xs text-[#6B6B6B] sm:flex-row">
          <p>© {new Date().getFullYear()} ReconDesk Inc. All rights reserved.</p>
          <p className="text-[11px] text-[#6B6B6B]">
            Built with precision for Chartered Accountants across India.
          </p>
        </div>
      </div>
    </footer>
  );
}
