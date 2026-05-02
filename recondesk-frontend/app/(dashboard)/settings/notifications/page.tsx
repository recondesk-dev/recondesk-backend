import Link from "next/link";

export default function NotificationsSettingsPlaceholderPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">
        Notifications
      </h1>
      <p className="text-sm text-[var(--text-secondary)]">
        Notification preferences will appear here.
      </p>
      <Link
        href="/settings"
        className="inline-flex min-h-[44px] items-center text-sm font-semibold text-[var(--accent)] underline"
      >
        ← Back to settings
      </Link>
    </div>
  );
}
