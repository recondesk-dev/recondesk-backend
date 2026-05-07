import Link from "next/link";

function LogoMark({ className = "" }: { className?: string }) {
  return (
    <div
      className={`flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--accent)] ${className}`}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="text-white" aria-hidden>
        <path
          d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 1-2-2V9m0 0h18"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

export function PublicNavbar() {
  return (
    <header className="sticky top-0 z-50 border-b border-white/10 bg-[#0a0c10]/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link href="/" className="flex items-center gap-2.5 text-white">
          <LogoMark />
          <span className="text-sm font-bold tracking-[0.2em]">RECONDESK</span>
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
