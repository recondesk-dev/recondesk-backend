"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

export default function ReconciliationResultPage() {
  const params = useParams();
  const runId = params?.run_id as string;

  return (
    <div className="mx-auto max-w-lg space-y-6 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8">
      <h1 className="text-lg font-semibold text-[var(--text-primary)]">Reconciliation complete</h1>
      <p className="text-sm text-[var(--text-secondary)]">
        Run <span className="font-mono">{runId}</span> finished successfully. Detailed results will appear here once
        wired to your reconciliation views.
      </p>
      <Link href="/" className="inline-block rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white">
        Back to Dashboard
      </Link>
    </div>
  );
}
