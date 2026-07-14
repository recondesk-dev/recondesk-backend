import Link from "next/link";

export function LegalPage({
  title,
  lastUpdated = "May 2026",
  children,
}: {
  title: string;
  lastUpdated?: string;
  children: React.ReactNode;
}) {
  return (
    <article className="mx-auto max-w-3xl px-4 py-12 sm:px-6 lg:px-8">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
        Last updated: {lastUpdated}
      </p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-[var(--ink)]">
        {title}
      </h1>
      <div className="mt-10 space-y-10 text-sm leading-relaxed text-gray-600">
        {children}
        <p className="pt-4 text-gray-500">
          <Link href="/" className="font-medium text-[var(--ink)] hover:underline">
            ← Back to home
          </Link>
        </p>
      </div>
    </article>
  );
}

export function LegalSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-[var(--ink)]">{title}</h2>
      {children}
    </section>
  );
}

export function LegalStrong({ children }: { children: React.ReactNode }) {
  return <strong className="font-semibold text-[var(--ink)]">{children}</strong>;
}
