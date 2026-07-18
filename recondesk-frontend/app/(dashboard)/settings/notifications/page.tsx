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
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center gap-4">
        <Link
          href="/settings"
          className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-white text-gray-500 shadow-[var(--shadow-soft)] transition hover:text-[var(--ink)]"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
            Notification Preferences
          </h1>
          <p className="text-sm text-gray-500">
            Control which email notifications you receive.
          </p>
        </div>
      </div>

      <div className="dashboard-card overflow-hidden">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-12 text-gray-500">
            <Loader2 className="h-8 w-8 animate-spin text-[var(--ink)]" />
            <span className="mt-2 text-sm">Loading preferences...</span>
          </div>
        ) : !preferences ? (
          <div className="p-6 text-center text-sm text-gray-500">
            Unable to load notification preferences. Please try reloading the page.
          </div>
        ) : (
          <div className="divide-y divide-[#F0F0F0]">
            <div className="flex items-start justify-between gap-6 p-5 transition duration-150 hover:bg-[#F7F7F8] md:p-6">
              <div className="space-y-1">
                <label
                  htmlFor="toggle-run-completed"
                  className="cursor-pointer text-sm font-semibold text-[var(--ink)]"
                >
                  Run Completed
                </label>
                <p className="text-xs leading-relaxed text-gray-500 md:text-sm">
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

            <div className="flex items-start justify-between gap-6 p-5 transition duration-150 hover:bg-[#F7F7F8] md:p-6">
              <div className="space-y-1">
                <label
                  htmlFor="toggle-runs-expiring"
                  className="cursor-pointer text-sm font-semibold text-[var(--ink)]"
                >
                  Runs Expiring Soon
                </label>
                <p className="text-xs leading-relaxed text-gray-500 md:text-sm">
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

            <div className="flex items-start justify-between gap-6 p-5 transition duration-150 hover:bg-[#F7F7F8] md:p-6">
              <div className="space-y-1">
                <label
                  htmlFor="toggle-payment-receipts"
                  className="cursor-pointer text-sm font-semibold text-[var(--ink)]"
                >
                  Payment Receipts
                </label>
                <p className="text-xs leading-relaxed text-gray-500 md:text-sm">
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

            <div className="flex items-start justify-between gap-6 p-5 transition duration-150 hover:bg-[#F7F7F8] md:p-6">
              <div className="space-y-1">
                <label
                  htmlFor="toggle-rule37-alerts"
                  className="cursor-pointer text-sm font-semibold text-[var(--ink)]"
                >
                  Rule 37 Payment Deadline Alerts
                </label>
                <p className="text-xs leading-relaxed text-gray-500 md:text-sm">
                  Get emailed when unpaid invoices approach the 180-day Rule 37 payment deadline (60-day and 30-day warnings) or become overdue.
                </p>
              </div>
              <div className="flex-shrink-0 pt-0.5">
                <Toggle
                  id="toggle-rule37-alerts"
                  checked={preferences.rule37_alerts !== false}
                  onChange={(checked) => handleToggle("rule37_alerts", checked)}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
