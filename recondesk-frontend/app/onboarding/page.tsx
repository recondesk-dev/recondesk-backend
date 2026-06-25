"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import { useToast } from "@/components/providers/ToastProvider";
import { getGstStateName, isValidGSTIN } from "@/components/ui/GstinInput";
import {
  clientsApi,
  isApiError,
  teamApi,
  type ClientGstin,
  type TeamMemberListItem,
} from "@/lib/api";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
} from "@/lib/auth-profile";
import { createClient, fetchAccessTokenFromServer } from "@/lib/supabase/client";
import { Logo } from "@/components/ui/Logo";

const STEPS = 4;

export default function OnboardingPage() {
  const router = useRouter();
  const toast = useToast();
  const [accessToken, setAccessToken] = useState<string | false | null>(null);
  const [step, setStep] = useState(1);

  const [gstin, setGstin] = useState("");
  const [gstinValid, setGstinValid] = useState<boolean | null>(null);
  const [gstinNorm, setGstinNorm] = useState("");
  const [gstinStateLabel, setGstinStateLabel] = useState("");
  const [gstinError, setGstinError] = useState("");
  const [gstinLoading, setGstinLoading] = useState(false);

  const [tradeName, setTradeName] = useState("");
  const [assignedTo, setAssignedTo] = useState("");
  const [clientId, setClientId] = useState<string | null>(null);
  const clientIdRef = useRef<string | null>(null);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitErr, setSubmitErr] = useState("");

  const [gstrFile, setGstrFile] = useState<File | null>(null);
  const [prFile, setPrFile] = useState<File | null>(null);

  useEffect(() => {
    clientIdRef.current = clientId;
  }, [clientId]);

  /** JWT for FastAPI: Supabase session first, then cookie-backed `/api/auth/access-token`. */
  useEffect(() => {
    const supabase = createClient();
    let cancelled = false;

    async function hydrateClients(authToken: string) {
      try {
        const clients = await clientsApi.list(authToken);
        if (!cancelled && clients?.length > 0) {
          setClientId((prev) => prev ?? clients[0].id);
        }
      } catch {
        /* ignore */
      }
    }

    async function resolveTokenFromSession(
      session: Awaited<ReturnType<typeof supabase.auth.getSession>>["data"]["session"]
    ): Promise<string | null> {
      const fromClient = session?.access_token ?? null;
      if (fromClient) return fromClient;
      const fromServer = await fetchAccessTokenFromServer();
      return typeof fromServer === "string" && fromServer.length > 0 ? fromServer : null;
    }

    async function applySession(
      session: Awaited<ReturnType<typeof supabase.auth.getSession>>["data"]["session"]
    ) {
      if (cancelled) return;
      const access = await resolveTokenFromSession(session);
      if (access) {
        setAccessToken(access);
        await hydrateClients(access);
      } else {
        setAccessToken(false);
      }
    }

    void (async () => {
      const { data } = await supabase.auth.getSession();
      await applySession(data.session);
    })();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      void applySession(session);
    });

    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, []);

  const token = typeof accessToken === "string" ? accessToken : null;
  const meKey = token ? (["onb-me", token] as const) : null;
  const teamKey = token ? (["onb-team", token] as const) : null;

  useEffect(() => {
    console.log("onboarding state:", {
      clientId,
      hasToken: !!token,
      gstrFile: !!gstrFile,
      prFile: !!prFile,
    });
  }, [clientId, token, gstrFile, prFile]);

  const { data: me } = useSWR(
    meKey,
    ([, t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );
  const { data: teamMembers } = useSWR(teamKey, ([, t]) => teamApi.list(t));

  const assignOptions = useMemo(() => {
    const opts: { userId: string; label: string }[] = [];
    if (me?.id) {
      opts.push({
        userId: me.id,
        label: `${me.full_name?.trim() || me.email || "You"} (Owner)`,
      });
    }
    (teamMembers as TeamMemberListItem[] | undefined)?.forEach((tm) => {
      if (tm.status !== "active" || !tm.member_user_id) return;
      if (tm.member_user_id === me?.id) return;
      opts.push({
        userId: tm.member_user_id,
        label: tm.full_name?.trim() || tm.email,
      });
    });
    return opts;
  }, [me, teamMembers]);

  const showAssignDropdown = assignOptions.length > 1;

  useEffect(() => {
    if (showAssignDropdown && assignedTo === "" && assignOptions[0]) {
      setAssignedTo(assignOptions[0].userId);
    }
    if (!showAssignDropdown && me?.id) {
      setAssignedTo(me.id);
    }
  }, [showAssignDropdown, assignOptions, assignedTo, me?.id]);

  const validateGstinRemote = useCallback(() => {
    const raw = gstin.trim();
    if (!raw) {
      setGstinValid(null);
      setGstinError("");
      setGstinNorm("");
      setGstinStateLabel("");
      return;
    }
    setGstinError("");
    if (isValidGSTIN(raw)) {
      setGstinValid(true);
      setGstinNorm(raw.toUpperCase());
      setGstinStateLabel("");
    } else {
      setGstinValid(false);
      setGstinNorm("");
      setGstinStateLabel("");
      setGstinError("Invalid GSTIN format — please check and re-enter");
    }
  }, [gstin]);

  const tradeOk = tradeName.trim().length >= 2;
  const canAddClient =
    gstinValid === true &&
    tradeOk &&
    !!token &&
    (!showAssignDropdown || !!assignedTo);

  const resolveClientIdByGstin = async (authToken: string): Promise<string | null> => {
    const norm = (gstinNorm || gstin.trim()).replace(/\s/g, "").toUpperCase();
    if (!norm) return null;
    try {
      const clients = await clientsApi.list(authToken);
      const row = clients.find(
        (c) => (c.gstin || "").replace(/\s/g, "").toUpperCase() === norm
      );
      return row?.id ?? null;
    } catch {
      return null;
    }
  };

  const onAddClient = async () => {
    if (!token || !canAddClient) return;
    setSubmitBusy(true);
    setSubmitErr("");
    try {
      const body: Parameters<typeof clientsApi.create>[1] = {
        gstin: gstinNorm || gstin.trim().toUpperCase(),
        trade_name: tradeName.trim(),
        assigned_to: assignedTo || undefined,
      };
      if (me?.email) body.contact_email = me.email;
      if (me?.full_name?.trim()) body.contact_name = me.full_name.trim();
      else body.contact_name = tradeName.trim();
      body.contact_phone =
        me?.phone && me.phone.replace(/\D/g, "").length >= 10
          ? me.phone.replace(/\D/g, "").slice(-10)
          : "0000000000";

      const created = await clientsApi.create(token, body);
      const fromResponse =
        created && typeof (created as ClientGstin).id === "string"
          ? (created as ClientGstin).id
          : null;
      const resolved = fromResponse?.length ? fromResponse : await resolveClientIdByGstin(token);
      if (resolved) {
        setClientId(resolved);
        setStep(3);
      } else {
        setSubmitErr("Could not determine client id after save. Try again or refresh.");
        toast("Could not determine client id after save.", "error");
      }
    } catch (e: unknown) {
      const existingId = await resolveClientIdByGstin(token);
      if (existingId) {
        setClientId(existingId);
        setStep(3);
      } else {
        setSubmitErr(isApiError(e) ? e.detail : "Could not add client.");
        toast(isApiError(e) ? e.detail : "Could not add client.", "error");
      }
    } finally {
      setSubmitBusy(false);
    }
  };

  const firstName = me?.full_name?.trim()?.split(/\s+/)[0] || "there";
  const progressPct = (step / STEPS) * 100;
  const gstStateName =
    gstinValid === true && isValidGSTIN(gstin) ? getGstStateName(gstin) : null;

  return (
    <div className="recondesk-textured-bg flex min-h-screen flex-col">
      <div className="fixed left-0 right-0 top-0 z-10 h-1 bg-violet-100">
        <div
          className="h-full bg-violet-600 transition-all duration-300"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      <header className="border-b border-gray-100 px-6 py-4">
        <div className="mx-auto flex max-w-[560px] items-center justify-between">
          <Logo className="text-gray-900" height="1.125rem" />
          <span className="text-xs text-gray-500">
            Step {step} of {STEPS}
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[560px] flex-1 px-6 py-10">
        {step === 1 && (
          <div className="space-y-8">
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">
                Welcome to ReconDesk, {firstName}!
              </h1>
              <p className="mt-2 text-sm text-gray-600">
                Let&apos;s run your first reconciliation in 5 minutes.
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-3">
              <div className="flex flex-col items-center gap-1 rounded-lg border border-gray-200 px-4 py-3">
                <UserIcon />
                <span className="text-center text-xs font-medium text-gray-700">
                  Add your client
                </span>
              </div>
              <span className="text-gray-400" aria-hidden>
                →
              </span>
              <div className="flex flex-col items-center gap-1 rounded-lg border border-gray-200 px-4 py-3">
                <UploadIcon />
                <span className="text-center text-xs font-medium text-gray-700">
                  Upload files
                </span>
              </div>
              <span className="text-gray-400" aria-hidden>
                →
              </span>
              <div className="flex flex-col items-center gap-1 rounded-lg border border-gray-200 px-4 py-3">
                <ChartIcon />
                <span className="text-center text-xs font-medium text-gray-700">
                  See results
                </span>
              </div>
            </div>

            <p className="text-center text-xs text-gray-500">
              No credit card needed — your first 2 reconciliations are free.
            </p>

            <button
              type="button"
              onClick={() => setStep(2)}
              className="flex h-12 w-full items-center justify-center rounded-full bg-violet-600 text-sm font-semibold text-white hover:bg-violet-700 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:ring-offset-2"
            >
              Get Started →
            </button>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-6">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="text-sm font-medium text-gray-600 hover:text-gray-900"
            >
              ← Back
            </button>
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">
                Add your first client
              </h1>
              <p className="mt-2 text-sm text-gray-600">
                Enter the GSTIN of the business you want to reconcile.
              </p>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                GSTIN
              </label>
              <div
                className={`relative rounded-lg border ${
                  gstinValid === true
                    ? "border-emerald-500 ring-1 ring-emerald-500"
                    : gstinValid === false
                      ? "border-red-500 ring-1 ring-red-500"
                      : "border-gray-300 focus-within:ring-2 focus-within:ring-violet-500"
                }`}
              >
                <input
                  className="w-full rounded-lg border-0 bg-transparent px-3 py-2.5 pr-10 text-sm outline-none"
                  placeholder="27AABCU9603R1ZX"
                  value={gstin}
                  onChange={(e) => {
                    setGstin(e.target.value.toUpperCase());
                    setGstinValid(null);
                    setGstinError("");
                  }}
                  onBlur={validateGstinRemote}
                />
                <div className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">
                  {gstinLoading ? (
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-violet-600 border-t-transparent" />
                  ) : gstinValid === true ? (
                    <span className="text-emerald-600" aria-hidden>
                      ✓
                    </span>
                  ) : gstinValid === false ? (
                    <span className="text-red-600" aria-hidden>
                      ✕
                    </span>
                  ) : null}
                </div>
              </div>
              {gstStateName && (
                <p className="mt-1 text-xs text-gray-500">
                  This GSTIN belongs to {gstStateName}
                </p>
              )}
              {gstinValid === false && gstinError && (
                <p className="mt-1 text-xs text-red-600">{gstinError}</p>
              )}
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">
                Trade name
              </label>
              <input
                className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-violet-500"
                placeholder="e.g. Sharma Textiles Pvt Ltd"
                value={tradeName}
                onChange={(e) => setTradeName(e.target.value)}
              />
            </div>

            {showAssignDropdown && (
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Assigned to
                </label>
                <select
                  className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:ring-2 focus:ring-violet-500"
                  value={assignedTo}
                  onChange={(e) => setAssignedTo(e.target.value)}
                >
                  {assignOptions.map((o) => (
                    <option key={o.userId} value={o.userId}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {submitErr && <p className="text-sm text-red-600">{submitErr}</p>}

            <button
              type="button"
              disabled={!canAddClient || submitBusy}
              onClick={() => void onAddClient()}
              className="flex h-12 w-full items-center justify-center rounded-full bg-violet-600 text-sm font-semibold text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:ring-offset-2"
            >
              {submitBusy ? "Saving…" : "Add Client →"}
            </button>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-6">
            <button
              type="button"
              onClick={() => setStep(2)}
              className="text-sm font-medium text-gray-600 hover:text-gray-900"
            >
              ← Back
            </button>
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">
                Download your GSTR-2B file
              </h1>
              <p className="mt-2 text-sm text-gray-600">
                You need the JSON file from the GST portal. Here&apos;s how:
              </p>
            </div>

            <ol className="list-decimal space-y-2 pl-5 text-sm text-gray-700">
              <li>
                Go to{" "}
                <a
                  href="https://www.gst.gov.in"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-violet-600 underline"
                >
                  gst.gov.in
                </a>{" "}
                and log in with your client&apos;s credentials
              </li>
              <li>Click Services → Returns → View Returns / Forms</li>
              <li>Select GSTR-2B and choose the month you want to reconcile</li>
              <li>Click Download → Download JSON</li>
              <li>Save the file — you&apos;ll upload it in the next step</li>
            </ol>

            <div className="rounded-lg bg-blue-50 px-4 py-3 text-sm text-blue-900">
              The JSON file is usually named GSTR2B_[GSTIN]_[period].json. File size is
              typically 1–10 MB depending on invoice count.
            </div>

            <a
              href="#"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-sm font-medium text-violet-600 hover:underline"
            >
              <PlayIcon />
              Watch our step-by-step video guide (Hindi)
            </a>

            <button
              type="button"
              onClick={() => setStep(4)}
              className="flex h-12 w-full items-center justify-center rounded-full bg-violet-600 text-sm font-semibold text-white hover:bg-violet-700"
            >
              I have the file →
            </button>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-6">
            <button
              type="button"
              onClick={() => setStep(3)}
              className="text-sm font-medium text-gray-600 hover:text-gray-900"
            >
              ← Back
            </button>
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">
                Upload your files and run reconciliation
              </h1>
              <p className="mt-2 text-sm text-gray-600">
                Upload the GSTR-2B JSON and your purchase register Excel.
              </p>
            </div>

            <FileDropZone
              label="Drop GSTR-2B JSON here or click to browse"
              accept=".json,application/json"
              file={gstrFile}
              onFile={setGstrFile}
            />
            <FileDropZone
              label="Drop Purchase Register Excel here or click to browse"
              accept=".xlsx,.xls,.csv"
              file={prFile}
              onFile={setPrFile}
            />

            <button
              type="button"
              disabled={!clientId || !gstrFile || !prFile}
              onClick={async () => {
                const id = clientIdRef.current || clientId;
                if (!id) return;

                console.log("button clicked, clientId:", clientId, "ref:", clientIdRef.current);

                const bearer = typeof accessToken === "string" ? accessToken : null;
                const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
                if (bearer) {
                  try {
                    const res = await fetch(`${apiBase}/api/v1/auth/onboarding-complete`, {
                      method: "POST",
                      headers: {
                        Authorization: `Bearer ${bearer}`,
                        "Content-Type": "application/json",
                      },
                    });
                    if (!res.ok) {
                      console.error("onboarding-complete failed:", res.status);
                    }
                  } catch (e) {
                    console.error("Failed to mark onboarding complete:", e);
                  }
                }

                router.refresh();
                router.push(`/reconcile/${id}/new`);
              }}
              className="flex h-12 w-full items-center justify-center rounded-full bg-violet-600 text-sm font-semibold text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Start Reconciliation →
            </button>
            <p className="text-center text-xs text-gray-500">
              This will use 1 of your 2 free reconciliations.
            </p>
            <p className="text-center text-xs text-gray-500">
              On the next screen, select the same files again to run the import wizard.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

function UserIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M12 11a4 4 0 100-8 4 4 0 000 8z"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M18 20V10M12 20V4M6 20v-6"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function PlayIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function FileDropZone({
  label,
  accept,
  file,
  onFile,
}: {
  label: string;
  accept: string;
  file: File | null;
  onFile: (f: File | null) => void;
}) {
  return (
    <label className="flex cursor-pointer flex-col rounded-lg border-2 border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-center hover:border-violet-400">
      <input
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
      <span className="text-sm text-gray-600">{label}</span>
      {file && (
        <span className="mt-2 text-xs font-medium text-violet-700">{file.name}</span>
      )}
    </label>
  );
}
