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
      <p className="text-xs font-medium uppercase tracking-wide text-[#6B6B6B]">
        Last updated: {lastUpdated}
      </p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-[#0A0A0A]">
        {title}
      </h1>
      <div className="mt-10 space-y-10 text-sm leading-relaxed text-[#3A3A3A]">
        {children}
        <p className="pt-4 text-[#6B6B6B]">
          <Link href="/" className="font-medium text-brand hover:underline">
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
      <h2 className="text-lg font-semibold text-[#0A0A0A]">{title}</h2>
      {children}
    </section>
  );
}

export function LegalStrong({ children }: { children: React.ReactNode }) {
  return <strong className="font-semibold text-[#0A0A0A]">{children}</strong>;
}
