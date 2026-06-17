"use client";

import Link from "next/link";
import useSWR, { mutate } from "swr";
import { ArrowLeft, Loader2 } from "lucide-react";

import { useToast } from "@/components/providers/ToastProvider";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { notificationsApi, type NotificationPreferences } from "@/lib/api";
import { Toggle } from "@/components/ui/Toggle";

export default function NotificationsSettingsPage() {
  const token = useAccessToken();
  const toast = useToast();

  const authToken = typeof token === "string" && token.length > 0 ? token : null;
  const resolvingToken = token === null;

  const cacheKey = authToken ? (["settings-notification-prefs", authToken] as const) : null;

  const { data: preferences, isLoading: prefsLoading } = useSWR(
    cacheKey,
    ([, t]) => notificationsApi.getPreferences(t),
    {
      revalidateOnFocus: false,
      shouldRetryOnError: false,
    }
  );

  const handleToggle = async (key: keyof NotificationPreferences, newValue: boolean) => {
    if (!authToken || !preferences) return;

    // Build updated preferences payload
    const updated = {
      ...preferences,
      [key]: newValue,
    };

    // Optimistic UI update
    mutate(cacheKey, updated, false);

    try {
      await notificationsApi.updatePreferences(authToken, updated);
      toast("Preferences saved", "success");
      // Force revalidation to make sure frontend matches server state
      mutate(cacheKey);
    } catch (err) {
      // Revert optimistic update on error
      mutate(cacheKey);
      toast("Failed to update notification settings. Please try again.", "error");
    }
  };

  const loading = resolvingToken || (!!authToken && prefsLoading);

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center gap-4">
        <Link
          href="/settings"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:shadow-sm transition"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">
            Notification Preferences
          </h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Control which email notifications you receive.
          </p>
        </div>
      </div>

      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-sm">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-12 text-[var(--text-secondary)]">
            <Loader2 className="h-8 w-8 animate-spin text-brand" />
            <span className="mt-2 text-sm">Loading preferences...</span>
          </div>
        ) : !preferences ? (
          <div className="p-6 text-center text-sm text-[var(--text-secondary)]">
            Unable to load notification preferences. Please try reloading the page.
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {/* Preference Row 1 */}
            <div className="flex items-start justify-between p-5 md:p-6 gap-6 hover:bg-gray-50/50 transition duration-150">
              <div className="space-y-1">
                <label
                  htmlFor="toggle-run-completed"
                  className="text-sm font-semibold text-[var(--text-primary)] cursor-pointer"
                >
                  Run Completed
                </label>
                <p className="text-xs md:text-sm text-[var(--text-secondary)] leading-relaxed">
                  Receive an email report once a reconciliation run finishes processing, summarizing matches, missed ITC, and at-risk claims.
                </p>
              </div>
              <div className="flex-shrink-0 pt-0.5">
                <Toggle
                  id="toggle-run-completed"
                  checked={preferences.run_completed}
                  onChange={(checked) => handleToggle("run_completed", checked)}
                />
              </div>
            </div>

            {/* Preference Row 2 */}
            <div className="flex items-start justify-between p-5 md:p-6 gap-6 hover:bg-gray-50/50 transition duration-150">
              <div className="space-y-1">
                <label
                  htmlFor="toggle-runs-expiring"
                  className="text-sm font-semibold text-[var(--text-primary)] cursor-pointer"
                >
                  Runs Expiring Soon
                </label>
                <p className="text-xs md:text-sm text-[var(--text-secondary)] leading-relaxed">
                  Get notified when a purchased run credit batch is within 7 days of its expiration date.
                </p>
              </div>
              <div className="flex-shrink-0 pt-0.5">
                <Toggle
                  id="toggle-runs-expiring"
                  checked={preferences.runs_expiring_soon}
                  onChange={(checked) => handleToggle("runs_expiring_soon", checked)}
                />
              </div>
            </div>

            {/* Preference Row 3 */}
            <div className="flex items-start justify-between p-5 md:p-6 gap-6 hover:bg-gray-50/50 transition duration-150">
              <div className="space-y-1">
                <label
                  htmlFor="toggle-payment-receipts"
                  className="text-sm font-semibold text-[var(--text-primary)] cursor-pointer"
                >
                  Payment Receipts
                </label>
                <p className="text-xs md:text-sm text-[var(--text-secondary)] leading-relaxed">
                  Receive a detailed email invoice and confirmation receipt immediately after making a successful payment.
                </p>
              </div>
              <div className="flex-shrink-0 pt-0.5">
                <Toggle
                  id="toggle-payment-receipts"
                  checked={preferences.payment_receipts}
                  onChange={(checked) => handleToggle("payment_receipts", checked)}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
