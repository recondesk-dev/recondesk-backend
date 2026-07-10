import { PublicFooter } from "@/components/public/PublicFooter";
import { PublicNavbar } from "@/components/public/PublicNavbar";

type MarketingPageLayoutProps = {
  children: React.ReactNode;
  className?: string;
  theme?: "light" | "dark" | "ledger";
};

export function MarketingPageLayout({
  children,
  className = "",
  theme = "light",
}: MarketingPageLayoutProps) {
  const isLedger = theme === "ledger";

  return (
    <div
      className={
        isLedger
          ? `min-h-screen min-w-0 bg-[#F2F3F5] text-[#3D4F63] antialiased ${className}`.trim()
          : `recondesk-textured-bg min-h-screen min-w-0 text-[#3A3A3A] antialiased ${className}`.trim()
      }
    >
      <PublicNavbar theme={theme === "dark" ? "dark" : theme === "ledger" ? "ledger" : "light"} />
      <main className="min-w-0">{children}</main>
      <PublicFooter theme={theme === "dark" ? "dark" : theme === "ledger" ? "ledger" : "light"} />
    </div>
  );
}
