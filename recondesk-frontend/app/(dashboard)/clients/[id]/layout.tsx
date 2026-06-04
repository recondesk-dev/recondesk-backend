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
    { label: "Communication", href: `/clients/${id}/communication` },
  ] as const;

  function isActive(href: string): boolean {
    if (href === `/clients/${id}`) {
      return pathname === href;
    }
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  return (
    <div>
      <nav className="border-b border-[var(--border)]">
        <div className="flex gap-6">
          {tabs.map(({ label, href }) => {
            const active = isActive(href);
            return (
              <Link
                key={href}
                href={href}
                className={
                  active
                    ? "-mb-px border-b-2 border-brand py-3 text-sm font-medium text-[var(--text-primary)]"
                    : "py-3 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
                }
              >
                {label}
              </Link>
            );
          })}
        </div>
      </nav>
      <div className="mt-8">{children}</div>
    </div>
  );
}
