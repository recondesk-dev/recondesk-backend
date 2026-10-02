import { PublicFooter } from "@/components/public/PublicFooter";
import { PublicNavbar } from "@/components/public/PublicNavbar";

type MarketingPageLayoutProps = {
  children: React.ReactNode;
  className?: string;
};

export function MarketingPageLayout({ children, className = "" }: MarketingPageLayoutProps) {
  return (
    <div
      className={`rd-public dashboard-soft-bg min-h-screen min-w-0 font-sans text-[var(--text-secondary)] antialiased ${className}`.trim()}
    >
      <PublicNavbar theme="light" />
      <main className="min-w-0">{children}</main>
      <PublicFooter theme="light" />
    </div>
  );
}
