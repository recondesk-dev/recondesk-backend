import React from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "next/link";
import {
  getAllPosts,
  getPostBySlug,
} from "@/lib/blog/posts";
import { MarkdownRenderer } from "@/components/blog/MarkdownRenderer";
import { BlogCard } from "@/components/blog/BlogCard";
import {
  ArrowLeft,
  Calendar,
  Clock,
  Share2,
  ShieldCheck,
  Sparkles,
  ArrowRight,
} from "lucide-react";

interface Props {
  params: {
    slug: string;
  };
}

export function generateStaticParams() {
  const posts = getAllPosts();
  return posts.map((post) => ({
    slug: post.slug,
  }));
}

export function generateMetadata({ params }: Props): Metadata {
  const post = getPostBySlug(params.slug);
  if (!post) {
    return {
      title: "Article Not Found — ReconDesk",
    };
  }

  return {
    title: `${post.title} — ReconDesk Intelligence`,
    description: post.excerpt,
    openGraph: {
      title: post.title,
      description: post.excerpt,
      type: "article",
      publishedTime: post.publishedAt,
      tags: post.tags,
    },
  };
}

export default function BlogPostPage({ params }: Props) {
  const post = getPostBySlug(params.slug);

  if (!post) {
    notFound();
  }

  const allPosts = getAllPosts();
  const relatedPosts = allPosts
    .filter((p) => p.slug !== post.slug)
    .slice(0, 2);

  return (
    <article className="bg-white text-[#0A0A0A] py-10 sm:py-16">
      <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">
        {/* Top Breadcrumb & Back Link */}
        <div className="flex items-center justify-between gap-4 text-xs text-[#6B6B6B]">
          <Link
            href="/blog"
            className="group inline-flex items-center gap-1.5 font-semibold text-[#0A0A0A] hover:text-[#7B5CFA] transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5 transition-transform group-hover:-translate-x-1" />
            <span>Back to All Articles</span>
          </Link>

          <div className="hidden sm:flex items-center gap-2">
            <span className="rounded-full bg-purple-100 text-[#7B5CFA] px-2.5 py-0.5 text-[11px] font-bold">
              {post.category}
            </span>
          </div>
        </div>

        {/* Post Header */}
        <header className="mt-8 pb-8 border-b border-[#E5E5E2]">
          <div className="flex items-center gap-2 text-xs font-semibold text-[#7B5CFA] uppercase tracking-wide">
            <span>{post.category}</span>
            <span>•</span>
            <div className="flex items-center gap-1 text-[#8C8C8C] normal-case">
              <Clock className="h-3 w-3" />
              <span>{post.readTime}</span>
            </div>
          </div>

          <h1 className="mt-3 text-2xl font-extrabold tracking-tight text-[#0A0A0A] sm:text-4xl lg:text-5xl leading-tight">
            {post.title}
          </h1>

          <p className="mt-4 text-base sm:text-lg text-[#6B6B6B] leading-relaxed">
            {post.excerpt}
          </p>

          {/* Author Strip */}
          <div className="mt-6 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#FAF9F5] text-sm font-bold text-[#7B5CFA] border border-[#E5E5E2]">
                {post.author.name.charAt(0)}
              </div>
              <div>
                <div className="text-xs sm:text-sm font-bold text-[#0A0A0A]">
                  {post.author.name}
                </div>
                <div className="text-[11px] text-[#8C8C8C] flex items-center gap-2">
                  <span>{post.author.role}</span>
                  <span>•</span>
                  <span className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    {post.publishedAt}
                  </span>
                </div>
              </div>
            </div>

            {/* Tags preview */}
            <div className="hidden sm:flex flex-wrap gap-1.5">
              {post.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-md bg-[#FAF9F5] border border-[#E5E5E2] px-2 py-0.5 text-[11px] text-[#6B6B6B]"
                >
                  #{tag}
                </span>
              ))}
            </div>
          </div>
        </header>

        {/* Main Article Body */}
        <div className="mt-10">
          <MarkdownRenderer content={post.content} />
        </div>

        {/* In-Article Conversion Banner */}
        <div className="my-14 rounded-2xl border border-purple-200 bg-gradient-to-r from-purple-50/60 to-white p-6 sm:p-8 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-6">
            <div className="space-y-2 max-w-lg">
              <span className="inline-flex items-center gap-1 rounded-full bg-purple-100 text-[#7B5CFA] px-2.5 py-0.5 text-[10px] font-bold">
                <Sparkles className="h-3 w-3" />
                <span>ReconDesk Decision Engine</span>
              </span>
              <h4 className="text-lg font-bold text-[#0A0A0A] sm:text-xl">
                Reconcile GSTR-2B with 5-Level Matching in 60 Seconds
              </h4>
              <p className="text-xs sm:text-sm text-[#6B6B6B]">
                Upload your client&apos;s purchase register and portal files. Let our fuzzy engine catch mismatches before statutory deadlines strike.
              </p>
            </div>
            <div className="shrink-0">
              <Link
                href="/auth/signup"
                className="inline-flex items-center gap-2 rounded-lg bg-[#7B5CFA] px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-[#6C4DE6] transition"
              >
                <span>Start Free Trial</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
        </div>

        {/* Related Articles */}
        {relatedPosts.length > 0 && (
          <section className="mt-16 border-t border-[#E5E5E2] pt-12">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold text-[#0A0A0A] sm:text-xl">
                Continue Reading
              </h3>
              <Link
                href="/blog"
                className="text-xs font-semibold text-[#7B5CFA] hover:text-[#6C4DE6]"
              >
                View all insights &rarr;
              </Link>
            </div>
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              {relatedPosts.map((related) => (
                <BlogCard key={related.slug} post={related} />
              ))}
            </div>
          </section>
        )}
      </div>
    </article>
  );
}
