"use client";

import React, { useState, useMemo } from "react";
import { BlogPost } from "@/lib/blog/types";
import { BlogCard } from "./BlogCard";
import { Search, Sparkles } from "lucide-react";
import Link from "next/link";

export function BlogCatalog({ posts }: { posts: BlogPost[] }) {
  const [selectedCategory, setSelectedCategory] = useState<string>("All");
  const [searchQuery, setSearchQuery] = useState<string>("");

  const categories = useMemo(() => {
    const list = Array.from(new Set(posts.map((p) => p.category)));
    return ["All", ...list];
  }, [posts]);

  const filteredPosts = useMemo(() => {
    return posts.filter((post) => {
      const matchesCategory =
        selectedCategory === "All" || post.category === selectedCategory;
      const matchesSearch =
        searchQuery.trim() === "" ||
        post.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        post.excerpt.toLowerCase().includes(searchQuery.toLowerCase()) ||
        post.tags.some((t) => t.toLowerCase().includes(searchQuery.toLowerCase()));
      return matchesCategory && matchesSearch;
    });
  }, [posts, selectedCategory, searchQuery]);

  const featuredPost = posts.find((p) => p.featured) || posts[0];

  return (
    <div>
      {/* Featured Article Hero (Shown if no filter active) */}
      {selectedCategory === "All" && searchQuery === "" && featuredPost && (
        <div className="mb-12 overflow-hidden rounded-2xl border border-[#E5E5E2] bg-gradient-to-br from-[#FAF9F5] via-white to-purple-50/30 p-6 sm:p-10 shadow-sm transition hover:border-[#7B5CFA]/40">
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6">
            <div className="space-y-3 max-w-2xl">
              <div className="flex items-center gap-2 text-xs">
                <span className="rounded-full bg-[#7B5CFA] px-2.5 py-0.5 font-bold text-white uppercase text-[10px] tracking-wide">
                  Featured Deep Dive
                </span>
                <span className="text-[#8C8C8C]">{featuredPost.category} • {featuredPost.readTime}</span>
              </div>
              <h2 className="text-xl sm:text-3xl font-extrabold tracking-tight text-[#0A0A0A] hover:text-[#7B5CFA] transition">
                <Link href={`/blog/${featuredPost.slug}`}>{featuredPost.title}</Link>
              </h2>
              <p className="text-xs sm:text-sm text-[#6B6B6B] leading-relaxed">
                {featuredPost.excerpt}
              </p>
              <div className="pt-2 flex items-center gap-3">
                <Link
                  href={`/blog/${featuredPost.slug}`}
                  className="inline-flex items-center gap-2 rounded-lg bg-[#7B5CFA] px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-[#6C4DE6] transition"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  <span>Read Flagship Analysis</span>
                </Link>
              </div>
            </div>

            <div className="hidden lg:block w-72 rounded-xl border border-purple-200 bg-white p-4 text-xs shadow-sm">
              <div className="font-bold text-[#0A0A0A]">What&apos;s inside:</div>
              <ul className="mt-2 space-y-2 text-[#6B6B6B]">
                <li className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#7B5CFA]" />
                  <span>Interactive Scrollytelling Demo</span>
                </li>
                <li className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#7B5CFA]" />
                  <span>Annual ITC Leakage Estimator</span>
                </li>
                <li className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#7B5CFA]" />
                  <span>Section 16(4) Action Checklist</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
        {/* Category Pills */}
        <div className="flex flex-wrap items-center gap-2">
          {categories.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => setSelectedCategory(cat)}
              className={`rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all ${
                selectedCategory === cat
                  ? "bg-[#0A0A0A] text-white shadow-sm"
                  : "border border-[#E5E5E2] bg-white text-[#6B6B6B] hover:border-[#0A0A0A] hover:text-[#0A0A0A]"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Search input */}
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[#8C8C8C]" />
          <input
            type="text"
            placeholder="Search insights..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-[#E5E5E2] bg-white py-1.5 pl-9 pr-3 text-xs text-[#0A0A0A] placeholder-[#8C8C8C] focus:border-[#7B5CFA] focus:outline-none focus:ring-1 focus:ring-[#7B5CFA]"
          />
        </div>
      </div>

      {/* Grid of posts */}
      {filteredPosts.length > 0 ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {filteredPosts.map((post) => (
            <BlogCard key={post.slug} post={post} />
          ))}
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-[#E5E5E2] p-12 text-center">
          <p className="text-sm font-semibold text-[#0A0A0A]">No articles found</p>
          <p className="mt-1 text-xs text-[#6B6B6B]">
            Try adjusting your search query or select another category.
          </p>
          <button
            type="button"
            onClick={() => {
              setSelectedCategory("All");
              setSearchQuery("");
            }}
            className="mt-4 rounded-md bg-[#FAF9F5] border border-[#E5E5E2] px-3 py-1.5 text-xs font-semibold text-[#0A0A0A] hover:bg-white"
          >
            Reset Filters
          </button>
        </div>
      )}
    </div>
  );
}
