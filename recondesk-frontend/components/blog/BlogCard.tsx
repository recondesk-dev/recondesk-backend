import React from "react";
import Link from "next/link";
import { ArrowRight, Clock, Calendar } from "lucide-react";
import { BlogPost } from "@/lib/blog/types";

export function BlogCard({ post }: { post: BlogPost }) {
  const categoryColors: Record<BlogPost["category"], string> = {
    "ITC Optimization": "bg-purple-100 text-[#7B5CFA] border-purple-200",
    "GST Compliance": "bg-emerald-100 text-emerald-700 border-emerald-200",
    "Tax Tech": "bg-blue-100 text-blue-700 border-blue-200",
    "CA Practice": "bg-amber-100 text-amber-800 border-amber-200",
  };

  const badgeClass =
    categoryColors[post.category] || "bg-gray-100 text-gray-700 border-gray-200";

  return (
    <article className="group flex flex-col justify-between rounded-xl border border-[#E5E5E2] bg-white p-5 sm:p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-[#7B5CFA]/40 hover:shadow-md">
      <div>
        {/* Top: Category & Read Time */}
        <div className="flex items-center justify-between gap-2 text-xs">
          <span
            className={`rounded-full border px-2.5 py-0.5 text-[11px] font-bold ${badgeClass}`}
          >
            {post.category}
          </span>
          <div className="flex items-center gap-1 text-[#8C8C8C]">
            <Clock className="h-3 w-3" />
            <span>{post.readTime}</span>
          </div>
        </div>

        {/* Title */}
        <h3 className="mt-4 text-base sm:text-lg font-bold tracking-tight text-[#0A0A0A] group-hover:text-[#7B5CFA] transition-colors">
          <Link href={`/blog/${post.slug}`}>
            {post.title}
          </Link>
        </h3>

        {/* Excerpt */}
        <p className="mt-2 text-xs sm:text-sm text-[#6B6B6B] line-clamp-3 leading-relaxed">
          {post.excerpt}
        </p>
      </div>

      {/* Bottom Footer: Author & Read More */}
      <div className="mt-6 flex items-center justify-between border-t border-[#F0F0EE] pt-4 text-xs">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-[#FAF9F5] text-[10px] font-bold text-[#7B5CFA] border border-[#E5E5E2]">
            {post.author.name.charAt(0)}
          </div>
          <div>
            <div className="font-semibold text-[#0A0A0A]">{post.author.name}</div>
            <div className="text-[10px] text-[#8C8C8C] flex items-center gap-1">
              <Calendar className="h-2.5 w-2.5" />
              <span>{post.publishedAt}</span>
            </div>
          </div>
        </div>

        <Link
          href={`/blog/${post.slug}`}
          className="flex items-center gap-1 font-semibold text-[#7B5CFA] group-hover:text-[#6C4DE6] transition-colors"
        >
          <span>Read</span>
          <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
        </Link>
      </div>
    </article>
  );
}
