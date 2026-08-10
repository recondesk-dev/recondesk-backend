"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

export default function ClientWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const pathname = usePathname();
  const id = params?.id as string;

  const tabs = [
    { label: "Overview", href: `/clients/${id}` },
    { label: "Annual Recon (FY)", href: `/clients/${id}/multi-period` },
    { label: "GSTR-9 & 9C", href: `/clients/${id}/gstr9` },
    { label: "GSTR-9C (ITC)", href: `/clients/${id}/gstr9c` },
    { label: "Follow-up History", href: `/clients/${id}/follow-up` },
    { label: "Communication", href: `/clients/${id}/communication` },
    { label: "Import Mapping", href: `/clients/${id}/import-mapping` },
  ] as const;

  function isActive(href: string): boolean {
    if (href === `/clients/${id}`) {
      return pathname === href;
    }
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  return (
    <div className="space-y-6">
      <nav className="flex flex-wrap gap-2">
        {tabs.map(({ label, href }) => {
          const active = isActive(href);
          return (
            <Link
              key={href}
              href={href}
              className={
                active
                  ? "rounded-full bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white shadow-sm"
                  : "rounded-full bg-white px-4 py-2 text-sm font-medium text-gray-500 shadow-[var(--shadow-soft)] transition-colors hover:text-[var(--ink)]"
              }
            >
              {label}
            </Link>
          );
        })}
      </nav>
      <div>{children}</div>
    </div>
  );
}
