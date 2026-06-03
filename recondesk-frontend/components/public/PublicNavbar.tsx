import Link from "next/link";

export function PublicNavbar() {
  return (
    <header className="sticky top-0 z-50 border-b border-white/10 bg-[#0a0c10]/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="font-brand inline-flex items-baseline gap-0 text-xl font-bold tracking-tight text-white sm:text-2xl"
        >
          <span>ReconDesk</span>
          <span className="text-xl leading-none text-purple-600 sm:text-2xl" aria-hidden="true">
            •
          </span>
        </Link>
        <nav className="flex items-center gap-3 sm:gap-6">
          <Link
            href="/pricing"
            className="text-sm font-medium text-slate-300 transition hover:text-white"
          >
            Pricing
          </Link>
          <Link
            href="/auth/login"
            className="text-sm font-medium text-slate-300 transition hover:text-white"
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
