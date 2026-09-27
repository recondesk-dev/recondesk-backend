import React from "react";
import Link from "next/link";
import { ArrowRight, BookOpen, Clock, Calendar, Sparkles } from "lucide-react";
import { getRecentPosts } from "@/lib/blog/posts";
import { BlogCard } from "@/components/blog/BlogCard";

export function BlogPreviewSection() {
  const recentPosts = getRecentPosts(3);
  const featured = recentPosts[0];

  return (
    <section id="blog" className="py-12 sm:py-20 border-t border-[#E5E5E2] bg-white">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between mb-8 sm:mb-10 gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-[#7B5CFA] flex items-center gap-1.5">
              <BookOpen className="h-3.5 w-3.5" />
              <span>Tax &amp; ITC Intelligence</span>
            </p>
            <h2 className="mt-2 text-2xl font-bold tracking-tight text-[#0A0A0A] sm:text-3xl">
              Actionable Insights for Modern CAs
            </h2>
            <p className="mt-2 max-w-xl text-xs sm:text-sm text-[#6B6B6B]">
              Deep-dives into GST statutory deadlines, Rule 36(4) compliance, and multi-level invoice matching.
            </p>
          </div>

          <Link
            href="/blog"
            className="group inline-flex items-center gap-1.5 text-xs font-bold text-[#7B5CFA] hover:text-[#6C4DE6] transition-colors"
          >
            <span>Explore All Insights</span>
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
          </Link>
        </div>

        {/* If 1 post: Showcase as a premium flagship card */}
        {recentPosts.length === 1 && featured ? (
          <div className="relative overflow-hidden rounded-2xl border border-[#E5E5E2] bg-gradient-to-br from-[#FAF9F5] via-white to-purple-50/40 p-6 sm:p-10 shadow-sm transition hover:border-[#7B5CFA]/40 hover:shadow-md">
            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-8">
              <div className="space-y-4 max-w-2xl">
                <div className="flex items-center gap-2 text-xs">
                  <span className="rounded-full bg-[#7B5CFA] px-2.5 py-0.5 font-bold text-white uppercase text-[10px] tracking-wide">
                    Flagship Guide
                  </span>
                  <span className="text-[#8C8C8C] flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {featured.readTime}
                  </span>
                  <span className="text-[#8C8C8C]">•</span>
                  <span className="text-[#8C8C8C] flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    {featured.publishedAt}
                  </span>
                </div>

                <h3 className="text-xl sm:text-3xl font-extrabold tracking-tight text-[#0A0A0A] hover:text-[#7B5CFA] transition-colors">
                  <Link href={`/blog/${featured.slug}`}>{featured.title}</Link>
                </h3>

                <p className="text-xs sm:text-sm text-[#6B6B6B] leading-relaxed">
                  {featured.excerpt}
                </p>

                <div className="pt-2 flex flex-wrap items-center gap-3">
                  <Link
                    href={`/blog/${featured.slug}`}
                    className="inline-flex items-center gap-2 rounded-lg bg-[#7B5CFA] px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-[#6C4DE6] transition"
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    <span>Read Complete Guide</span>
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>

                  <Link
                    href="/blog"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[#E5E5E2] bg-white px-4 py-2 text-xs font-semibold text-[#0A0A0A] hover:bg-[#FAF9F5] transition"
                  >
                    View All Articles
                  </Link>
                </div>
              </div>

              {/* What's inside box */}
              <div className="w-full lg:w-80 rounded-xl border border-purple-200/80 bg-white p-5 text-xs shadow-xs space-y-3">
                <div className="font-bold text-[#0A0A0A] flex items-center gap-1.5 text-purple-900">
                  <Sparkles className="h-3.5 w-3.5 text-[#7B5CFA]" />
                  <span>Interactive Highlights:</span>
                </div>
                <ul className="space-y-2 text-[#4A4A4A]">
                  <li className="flex items-start gap-2">
                    <span className="mt-1 h-1.5 w-1.5 rounded-full bg-[#7B5CFA] shrink-0" />
                    <span>Forensic Audit Loupe (Tally vs GSTN X-Ray)</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="mt-1 h-1.5 w-1.5 rounded-full bg-[#7B5CFA] shrink-0" />
                    <span>GSTR-2A vs GSTR-2B Legal Vault Switcher</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="mt-1 h-1.5 w-1.5 rounded-full bg-[#7B5CFA] shrink-0" />
                    <span>Rule 36(4) Statutory Compliance Checklist</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
            {recentPosts.map((post) => (
              <BlogCard key={post.slug} post={post} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
