import Link from "next/link";

type PublicNavbarProps = {
  theme?: "dark" | "light";
};

export function PublicNavbar({ theme = "dark" }: PublicNavbarProps) {
  const isLight = theme === "light";

  return (
    <header
      className={
        isLight
          ? "sticky top-0 z-50 border-b border-[#E5E5E5] bg-white"
          : "sticky top-0 z-50 border-b border-white/10 bg-[#0a0c10]/85 backdrop-blur-md"
      }
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className={`font-brand inline-flex items-baseline gap-0 text-2xl font-bold tracking-tight sm:text-3xl ${
            isLight ? "text-[#0A0A0A]" : "text-white"
          }`}
        >
          <span>ReconDesk</span>
          <span className="text-2xl leading-none text-purple-600 sm:text-3xl" aria-hidden="true">
            •
          </span>
        </Link>
        <nav className="flex items-center gap-3 sm:gap-6">
          <Link
            href="/pricing"
            className={
              isLight
                ? "text-sm font-medium text-[#3A3A3A] transition hover:text-[#0A0A0A]"
                : "text-sm font-medium text-slate-300 transition hover:text-white"
            }
          >
            Pricing
          </Link>
          <Link
            href="/auth/login"
            className={
              isLight
                ? "text-sm font-medium text-[#3A3A3A] transition hover:text-[#0A0A0A]"
                : "text-sm font-medium text-slate-300 transition hover:text-white"
            }
          >
            Login
          </Link>
          <Link
            href="/auth/signup"
            className="inline-flex min-h-[40px] items-center justify-center rounded-lg bg-[var(--accent)] px-4 text-sm font-semibold text-white shadow-sm transition hover:opacity-95"
          >
            Start Free
          </Link>
        </nav>
      </div>
    </header>
  );
}
