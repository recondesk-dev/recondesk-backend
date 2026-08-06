"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import useSWR, { mutate } from "swr";
import {
  ArrowLeft,
  Check,
  Copy,
  Download,
  KeyRound,
  Loader2,
} from "lucide-react";

import { useToast } from "@/components/providers/ToastProvider";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { isApiError, tallyBridgeApi } from "@/lib/api";

function formatSyncedAgo(iso: string | null | undefined): string {
  if (!iso) return "Never synced";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "Never synced";
  const diffMs = Date.now() - t;
  if (diffMs < 0) return "Just now";
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

async function downloadAuthed(url: string, token: string, filename: string) {
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
    redirect: "manual",
  });
  // Published exe may be a Release/CDN URL — follow outside the blob path.
  if (
    res.status === 301 ||
    res.status === 302 ||
    res.status === 303 ||
    res.status === 307 ||
    res.status === 308
  ) {
    const loc = res.headers.get("Location");
    if (!loc) {
      throw new Error("Download redirect missing Location header");
    }
    const a = document.createElement("a");
    a.href = loc;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    return;
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Download failed (${res.status})`);
  }
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

export default function TallyBridgeSetupPage() {
  const token = useAccessToken();
  const toast = useToast();
  const authToken = typeof token === "string" && token.length > 0 ? token : null;

  const statusKey = authToken
    ? (["tally-bridge-status", authToken] as const)
    : null;
  const { data: status, isLoading } = useSWR(
    statusKey,
    ([, t]) => tallyBridgeApi.status(t),
    { refreshInterval: 60_000 }
  );

  const [companyName, setCompanyName] = useState("");
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [downloading, setDownloading] = useState<
    "exe" | "agent" | "config" | null
  >(null);

  const lastSyncedLabel = useMemo(
    () => formatSyncedAgo(status?.last_synced_at),
    [status?.last_synced_at]
  );

  const createKey = useCallback(async () => {
    if (!authToken) return;
    setCreating(true);
    setCopied(false);
    try {
      const res = await tallyBridgeApi.createKey(authToken, companyName.trim());
      setNewKey(res.api_key);
      toast("API key generated — copy it now; it won’t be shown again", "success");
      if (statusKey) mutate(statusKey);
    } catch (err) {
      toast(
        isApiError(err) ? err.detail : "Failed to generate API key",
        "error"
      );
    } finally {
      setCreating(false);
    }
  }, [authToken, companyName, toast, statusKey]);

  const copyKey = useCallback(async () => {
    if (!newKey) return;
    try {
      await navigator.clipboard.writeText(newKey);
      setCopied(true);
      toast("API key copied", "success");
    } catch {
      toast("Could not copy — select and copy manually", "error");
    }
  }, [newKey, toast]);

  const download = useCallback(
    async (kind: "exe" | "agent" | "config") => {
      if (!authToken) return;
      setDownloading(kind);
      try {
        if (kind === "exe") {
          await downloadAuthed(
            tallyBridgeApi.agentExeDownloadUrl(),
            authToken,
            "ReconDeskTallyBridge.exe"
          );
        } else if (kind === "agent") {
          await downloadAuthed(
            tallyBridgeApi.agentDownloadUrl(),
            authToken,
            "tally_bridge_agent.py"
          );
        } else {
          await downloadAuthed(
            tallyBridgeApi.configExampleDownloadUrl(),
            authToken,
            "tally_bridge.config.example.json"
          );
        }
        toast("Download started", "success");
      } catch (err) {
        toast(err instanceof Error ? err.message : "Download failed", "error");
      } finally {
        setDownloading(null);
      }
    },
    [authToken, toast]
  );

  const loading = token === null || (!!authToken && isLoading);

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
            Tally Bridge Setup
          </h1>
          <p className="text-sm text-gray-500">
            Sync Bills Payable (still unpaid), Payment Agst Ref vouchers,
            Purchase Register, and Ledger Masters (GSTIN & State) from
            Tally. Auto-settle only from payments when party name confidence is
            high; weak party matches are flagged for manual confirmation.
          </p>
        </div>
      </div>

      {loading ? (
        <div className="dashboard-card flex items-center gap-3 px-5 py-8 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      ) : (
        <>
          <section className="dashboard-card p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-[var(--ink)]">
                  Sync status
                </h2>
                <p className="mt-1 text-sm text-gray-500">
                  {status?.has_key
                    ? "An API key is configured for this workspace."
                    : "Generate an API key to connect the local agent."}
                </p>
              </div>
              <div className="rounded-full bg-[#F3F4F6] px-4 py-2 text-sm font-medium text-[var(--ink)]">
                Last synced: {lastSyncedLabel}
              </div>
            </div>
          </section>

          <section className="dashboard-card space-y-4 p-6">
            <div className="flex items-center gap-3">
              <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-[#F3F4F6] text-gray-700">
                <KeyRound className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-base font-semibold text-[var(--ink)]">
                  API key
                </h2>
                <p className="text-sm text-gray-500">
                  Paste into the agent config as{" "}
                  <code className="text-[12px]">api_key</code>. Shown once.
                </p>
              </div>
            </div>

            <label className="block text-sm">
              <span className="mb-1.5 block text-gray-500">
                Tally company name (optional)
              </span>
              <input
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="As shown in Tally"
                className="w-full rounded-xl border border-[#E5E5E5] bg-white px-3.5 py-2.5 text-sm text-[var(--ink)] outline-none transition focus:border-gray-400"
              />
            </label>

            <button
              type="button"
              onClick={createKey}
              disabled={!authToken || creating}
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {creating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <KeyRound className="h-4 w-4" />
              )}
              Generate API key
            </button>

            {newKey ? (
              <div className="rounded-xl border border-[#E5E5E5] bg-[#FAFAFA] p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
                  New key
                </p>
                <code className="mt-2 block break-all text-[13px] text-[var(--ink)]">
                  {newKey}
                </code>
                <button
                  type="button"
                  onClick={copyKey}
                  className="mt-3 inline-flex min-h-[40px] items-center gap-2 rounded-full bg-[#F3F4F6] px-4 text-sm font-medium text-[var(--ink)] transition hover:bg-gray-200/70"
                >
                  {copied ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                  {copied ? "Copied" : "Copy key"}
                </button>
              </div>
            ) : null}
          </section>

          <section className="dashboard-card space-y-4 p-6">
            <h2 className="text-base font-semibold text-[var(--ink)]">
              Local agent
            </h2>
            <p className="text-sm text-gray-500">
              Run on the CA machine with Tally open and XML server enabled
              (F1 → Settings → Connectivity). Download the Windows{" "}
              <code className="text-[12px]">.exe</code> — no Python install
              needed. Place{" "}
              <code className="text-[12px]">tally_bridge.config.json</code> next
              to the executable. The agent exports Bills Payable (unpaid check
              only — never settle), Day Book Payment vouchers (settle
              evidence), Purchase Register, and Ledger Masters (GSTIN & State
              sync). Start with{" "}
              <code className="text-[12px]">--test</code> to validate
              exports: it prints per-export row counts and warns if any is
              zero.
            </p>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => download("exe")}
                disabled={!authToken || downloading !== null}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {downloading === "exe" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
                Download Windows agent (.exe)
              </button>
              <button
                type="button"
                onClick={() => download("config")}
                disabled={!authToken || downloading !== null}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-full bg-[#F3F4F6] px-5 text-sm font-semibold text-[var(--ink)] transition hover:bg-gray-200/70 disabled:opacity-50"
              >
                {downloading === "config" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
                Config example
              </button>
              <button
                type="button"
                onClick={() => download("agent")}
                disabled={!authToken || downloading !== null}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-full bg-[#F3F4F6] px-5 text-sm font-semibold text-[var(--ink)] transition hover:bg-gray-200/70 disabled:opacity-50"
              >
                {downloading === "agent" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
                Python script (advanced)
              </button>
            </div>
            <pre className="overflow-x-auto rounded-xl bg-[#0F1117] px-4 py-3 text-[12px] leading-relaxed text-gray-200">
{`ReconDeskTallyBridge.exe --config tally_bridge.config.json --test`}
            </pre>
          </section>
        </>
      )}
    </div>
  );
}
