import React from "react";
import type { Metadata } from "next";
import { getAllPosts } from "@/lib/blog/posts";
import { BlogCatalog } from "@/components/blog/BlogCatalog";
import { Sparkles, ShieldCheck } from "lucide-react";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Blog & Tax Intelligence — ReconDesk",
  description:
    "Actionable tax intelligence, statutory circular breakdowns, and algorithmic ITC reconciliation insights for Chartered Accountants.",
};

export default function BlogHubPage() {
  const posts = getAllPosts();

  return (
    <div className="bg-white text-[#0A0A0A] py-12 sm:py-16">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Header Banner */}
        <div className="text-center max-w-2xl mx-auto mb-12">
          <p className="text-xs font-bold uppercase tracking-widest text-[#7B5CFA] flex items-center justify-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5" />
            <span>Research &amp; Engineering</span>
          </p>
          <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl">
            ReconDesk Tax &amp; ITC Intelligence
          </h1>
          <p className="mt-3 text-sm text-[#6B6B6B] leading-relaxed">
            Curated analysis on GST statutory deadlines, Rule 37A compliance, notice defense frameworks, and multi-level invoice matching.
          </p>
        </div>

        {/* Catalog */}
        <BlogCatalog posts={posts} />

        {/* Bottom CTA Banner */}
        <div className="mt-16 rounded-2xl border border-[#E5E5E2] bg-[#FAF9F5] p-8 text-center sm:p-12">
          <h3 className="text-xl font-bold text-[#0A0A0A] sm:text-2xl">
            Never Let Eligible ITC Lapse Again
          </h3>
          <p className="mx-auto mt-2 max-w-xl text-xs sm:text-sm text-[#6B6B6B]">
            Automate 5-level invoice matching for your CA firm. Claim 100% of eligible ITC with audit-ready workpapers in under 60 seconds.
          </p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/auth/signup"
              className="rounded-lg bg-[#7B5CFA] px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-[#6C4DE6] transition"
            >
              Start 60-Day Free Trial
            </Link>
            <Link
              href="/depth"
              className="rounded-lg border border-[#E5E5E2] bg-white px-5 py-2.5 text-xs font-semibold text-[#0A0A0A] hover:bg-[#FAF9F5] transition"
            >
              Explore ReconDepth Specs
            </Link>
          </div>
          <div className="mt-4 flex items-center justify-center gap-2 text-[11px] text-[#8C8C8C]">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
            <span>2 GSTINs Free • Zero Credit Card Required</span>
          </div>
        </div>
      </div>
    </div>
  );
}
