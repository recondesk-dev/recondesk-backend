export default function TermsPage() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
      <h1 className="text-2xl font-semibold text-white">Terms of Service</h1>
      <p className="mt-4 text-sm leading-relaxed text-slate-400">
        Terms of service for ReconDesk will be published here. For questions, contact{" "}
        <a href="mailto:hello@recondesk.in" className="text-[var(--accent)] hover:underline">
          hello@recondesk.in
        </a>
        .
      </p>
    </div>
  );
}
