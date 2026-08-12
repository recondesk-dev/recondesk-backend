"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { useRouter, useSearchParams } from "next/navigation";

import { Modal } from "@/components/ui/Modal";
import { ConnectGstnModal } from "@/components/clients/ConnectGstnModal";
import { EmptyStateIllustration } from "@/components/ui/EmptyStateIllustration";
import { GstinInput, validateGstin } from "@/components/ui/GstinInput";
import { useToast } from "@/components/providers/ToastProvider";
import {
  billingApi,
  clientsApi,
  isApiError,
  teamApi,
  type ClientGstin,
  type TeamMemberListItem,
} from "@/lib/api";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
  normalizeAuthRole,
} from "@/lib/auth-profile";
import { useAccessToken } from "@/lib/hooks/useAccessToken";

const CLIENTS_KEY = "backend-clients-list";

function useDebounced<T>(value: T, ms: number): T {
  const [d, setD] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setD(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return d;
}

function ClientsSkeleton() {
  return (
    <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
      <div className="animate-pulse space-y-0">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div
            key={i}
            className="flex gap-4 border-b border-[#F0F0F0] px-5 py-4 last:border-b-0"
          >
            <div className="h-4 flex-1 rounded bg-gray-100" />
            <div className="h-4 w-40 rounded bg-gray-100" />
            <div className="h-10 w-44 rounded-full bg-gray-100" />
          </div>
        ))}
      </div>
    </div>
  );
}

function assignLabel(
  assignedTo: string | null | undefined,
  map: Map<string, string>
): string {
  if (!assignedTo) return "—";
  return map.get(assignedTo) ?? `${assignedTo.slice(0, 8)}…`;
}

export function ClientsPageContent() {
  const toast = useToast();
  const router = useRouter();
  const searchParams = useSearchParams();
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0
      ? tokenState
      : null;

  const meKey = authToken ? (["clients-me", authToken] as const) : null;
  const teamKey = authToken ? (["clients-team", authToken] as const) : null;
  const clientsKey =
    authToken ? ([CLIENTS_KEY, authToken] as const) : null;

  const { data: me } = useSWR(
    meKey,
    ([, t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );
  const { data: teamMembers } = useSWR(teamKey, ([, t]) => teamApi.list(t));
  const billingKey = authToken ? (["clients-billing", authToken] as const) : null;
  const { data: billingStatus, mutate: mutateBilling } = useSWR(
    billingKey,
    ([, t]) => billingApi.status(t)
  );
  const {
    data: clients,
    error: clientsError,
    isLoading: clientsLoading,
    mutate: mutateClients,
  } = useSWR(
    clientsKey,
    ([, t]) => clientsApi.list(t),
    { keepPreviousData: true }
  );

  const roleNorm = normalizeAuthRole(me?.role);
  const isAdmin = roleNorm === "admin";

  const assigneeNames = useMemo(() => {
    const m = new Map<string, string>();
    if (me?.id) {
      m.set(me.id, me.full_name?.trim() || me.email || "Owner");
    }
    (teamMembers as TeamMemberListItem[] | undefined)?.forEach((tm) => {
      if (tm.status === "active" && tm.member_user_id) {
        const label = tm.full_name?.trim() || tm.email;
        m.set(tm.member_user_id, label);
      }
    });
    return m;
  }, [me, teamMembers]);

  const assignOptions = useMemo(() => {
    const opts: { userId: string; label: string }[] = [];
    if (me?.id) {
      opts.push({
        userId: me.id,
        label: `${me.full_name?.trim() || me.email || "Owner"} (Owner)`,
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

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounced(search, 200);

  const [addOpen, setAddOpen] = useState(false);
  const [formGstin, setFormGstin] = useState("");
  const [formTradeName, setFormTradeName] = useState("");
  const [formContactName, setFormContactName] = useState("");
  const [formContactEmail, setFormContactEmail] = useState("");
  const [formContactPhone, setFormContactPhone] = useState("");
  const [formAssignedTo, setFormAssignedTo] = useState("");
  const [addBusy, setAddBusy] = useState(false);

  // ── GSTIN verification state ──────────────────────────────────────────────
  type VerifyResult = {
    valid: boolean;
    status: string;
    legal_name: string | null;
    trade_name: string | null;
  };
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);
  const [verifyBusy, setVerifyBusy] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  // Track which GSTIN the current result belongs to so we reset on change
  const verifiedForRef = useRef<string>("");
  const [saveWarning, setSaveWarning] = useState<string | null>(null);
  const addQueryHandledRef = useRef(false);

  const filtered = useMemo(() => {
    const list = clients ?? [];
    const q = debouncedSearch.trim().toLowerCase();
    if (!q) return list;
    return list.filter((c) => {
      const name = (c.trade_name ?? "").toLowerCase();
      const gst = (c.gstin ?? "").toLowerCase();
      return name.includes(q) || gst.includes(q);
    });
  }, [clients, debouncedSearch]);

  useEffect(() => {
    if (addOpen && assignOptions.length && !formAssignedTo) {
      setFormAssignedTo(assignOptions[0]?.userId ?? "");
    }
  }, [addOpen, assignOptions, formAssignedTo]);

  const [connectTarget, setConnectTarget] = useState<{ id: string; gstin: string } | null>(null);


  const gstinOk = validateGstin(formGstin).status === "valid";
  const canSubmitAdd =
    gstinOk &&
    formTradeName.trim().length >= 2 &&
    formContactName.trim().length >= 1 &&
    formContactEmail.includes("@") &&
    formContactPhone.trim().length >= 6 &&
    !!formAssignedTo;

  const gstinLimit = billingStatus?.gstin_limit ?? 1;
  const gstinsUsed = billingStatus?.gstins_used ?? 0;
  const atGstinLimit =
    billingStatus != null && gstinsUsed >= gstinLimit;

  const openAddClient = () => {
    if (atGstinLimit) {
      toast(
        `GSTIN limit reached (${gstinsUsed}/${gstinLimit}). Upgrade on Billing to add more clients.`,
        "error"
      );
      router.push("/billing");
      return;
    }
    resetAddForm();
    setAddOpen(true);
  };

  const resetAddForm = () => {
    setFormGstin("");
    setFormTradeName("");
    setFormContactName("");
    setFormContactEmail("");
    setFormContactPhone("");
    setFormAssignedTo(assignOptions[0]?.userId ?? "");
    setVerifyResult(null);
    setVerifyBusy(false);
    setVerifyError(null);
    setSaveWarning(null);
    verifiedForRef.current = "";
  };

  useEffect(() => {
    if (searchParams.get("add") !== "1") return;
    if (addQueryHandledRef.current) return;
    if (typeof window !== "undefined") {
      window.history.replaceState({}, "", "/clients");
    }
    // Wait for billing status so free-tier limit can gate the modal.
    if (billingStatus === undefined) return;
    addQueryHandledRef.current = true;
    openAddClient();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- open-once from query; avoid re-running when form changes
  }, [searchParams, billingStatus]);

  // Reset verify result whenever the GSTIN changes
  useEffect(() => {
    const upper = formGstin.trim().toUpperCase();
    if (upper !== verifiedForRef.current) {
      setVerifyResult(null);
      setVerifyError(null);
    }
  }, [formGstin]);

  const handleVerifyGstin = async () => {
    if (!authToken || !gstinOk) return;
    const gstin = formGstin.trim().toUpperCase();
    setVerifyBusy(true);
    setVerifyResult(null);
    setVerifyError(null);
    try {
      const res = await clientsApi.gstinVerify(authToken, gstin);
      setVerifyResult(res);
      verifiedForRef.current = gstin;
      // Pre-fill trade name from verified data if the field is still blank
      if (!formTradeName.trim() && (res.trade_name || res.legal_name)) {
        setFormTradeName((res.trade_name ?? res.legal_name ?? "").trim());
      }
    } catch {
      setVerifyError("Verification unavailable — you may proceed manually.");
    } finally {
      setVerifyBusy(false);
    }
  };

  const submitAdd = async () => {
    if (!authToken || !canSubmitAdd) return;
    setAddBusy(true);
    setSaveWarning(null);
    try {
      const result = await clientsApi.create(authToken, {
        gstin: formGstin.trim().toUpperCase(),
        trade_name: formTradeName.trim(),
        contact_name: formContactName.trim(),
        contact_email: formContactEmail.trim(),
        contact_phone: formContactPhone.trim(),
        assigned_to: formAssignedTo || undefined,
      });
      if (result.gstin_verification_warning) {
        setSaveWarning(result.gstin_verification_warning);
      } else {
        toast("Client added. Connect GSTN via OTP next!", "success");
        setAddOpen(false);
        resetAddForm();
        setConnectTarget({ id: result.id, gstin: result.gstin });
      }
      await mutateClients();
      void mutateBilling();
    } catch (e: unknown) {
      const detail = isApiError(e) ? e.detail : "Could not add client.";
      toast(detail, "error");
      if (
        isApiError(e) &&
        typeof e.detail === "string" &&
        e.detail.includes("GSTIN limit reached")
      ) {
        router.push("/billing");
      }
    } finally {
      setAddBusy(false);
    }
  };

  const handleAssign = async (clientId: string, assignedTo: string) => {
    if (!authToken) return;
    try {
      await clientsApi.assign(authToken, clientId, assignedTo);
      toast("Client assigned", "success");
      await mutateClients();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Assignment failed.", "error");
      await mutateClients();
    }
  };

  const handleDelete = async (row: ClientGstin) => {
    if (!authToken || !isAdmin) return;
    if (
      typeof window !== "undefined" &&
      !window.confirm(`Remove client ${row.trade_name ?? row.gstin}?`)
    ) {
      return;
    }
    try {
      await clientsApi.delete(authToken, row.id);
      toast("Client removed", "success");
      await mutateClients();
      void mutateBilling();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Could not remove client.", "error");
    }
  };

  const resolvingToken = tokenState === null;
  const showSkeleton =
    resolvingToken || (!!authToken && clientsLoading && !clients);

  const showEmpty =
    !showSkeleton &&
    !clientsError &&
    authToken &&
    Array.isArray(clients) &&
    clients.length === 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--ink)]">
            Clients
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            GSTINs in your portfolio and who they are assigned to
          </p>
        </div>
        <button
          type="button"
          className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
          onClick={openAddClient}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
            <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          Add Client
        </button>
      </div>

      {clientsError && (
        <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
          Could not load clients.{" "}
          <button
            type="button"
            className="font-semibold text-[var(--ink)] underline"
            onClick={() => void mutateClients()}
          >
            Retry
          </button>
        </div>
      )}

      {!authToken && tokenState === false && (
        <div className="rounded-[1.25rem] bg-amber-50 px-5 py-4 text-sm text-amber-950">
          Sign in to load clients from your workspace.
        </div>
      )}

      {showEmpty ? (
        <div className="dashboard-card flex min-h-[320px] flex-col items-center justify-center px-6 py-16 text-center">
          <div className="mx-auto w-full max-w-[400px]">
            <EmptyStateIllustration className="mx-auto text-gray-300" />
            <h2 className="mt-4 text-lg font-semibold text-[var(--ink)]">
              No clients added yet
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              Each client is a GSTIN you reconcile monthly
            </p>
            <button
              type="button"
              className="mt-6 inline-flex min-h-[44px] w-full max-w-xs items-center justify-center rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
              onClick={openAddClient}
            >
              Add Client
            </button>
          </div>
        </div>
      ) : (
        <section className="dashboard-card space-y-5 p-6">
          <div className="relative max-w-md">
            <svg
              className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden
            >
              <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.5" />
              <path d="M20 20l-3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-full border-0 bg-[#F5F5F6] py-2.5 pl-10 pr-4 text-sm font-medium text-gray-700 outline-none transition-shadow placeholder:text-gray-400 focus:ring-2 focus:ring-black/10"
              placeholder="Search trade name or GSTIN"
            />
          </div>

          {showSkeleton ? (
            <ClientsSkeleton />
          ) : (
            <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
              <div className="overflow-x-auto">
                <table className="min-w-[860px] w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
                      <th className="px-5 py-4">Trade Name</th>
                      <th className="px-4 py-4">GSTIN</th>
                      <th className="px-4 py-4">Assign To</th>
                      {isAdmin && (
                        <th className="px-5 py-4 text-right">Actions</th>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((row) => (
                      <tr
                        key={row.id}
                        className="border-b border-[#F0F0F0] transition-colors hover:bg-[#F7F7F8] last:border-b-0"
                      >
                        <td className="px-5 py-3.5">
                          <Link
                            href={`/clients/${row.id}`}
                            className="font-medium text-[var(--ink)] hover:underline cursor-pointer"
                          >
                            {row.trade_name ?? "—"}
                          </Link>
                        </td>
                        <td className="px-4 py-3.5 font-mono text-xs text-gray-500">
                          {row.gstin}
                        </td>
                        <td className="px-4 py-3.5">
                          {isAdmin ? (
                            <select
                              className="min-h-[40px] w-full max-w-[260px] rounded-full border-0 bg-[#F5F5F6] px-4 text-sm font-medium text-gray-700 outline-none focus:ring-2 focus:ring-black/10"
                              value={
                                row.assigned_to ??
                                assignOptions[0]?.userId ??
                                ""
                              }
                              onChange={(e) =>
                                void handleAssign(row.id, e.target.value)
                              }
                              disabled={!assignOptions.length}
                            >
                              {assignOptions.map((o) => (
                                <option key={o.userId} value={o.userId}>
                                  {o.label}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <span className="text-gray-500">
                              {assignLabel(row.assigned_to, assigneeNames)}
                            </span>
                          )}
                        </td>
                        {isAdmin && (
                          <td className="px-5 py-3.5 text-right">
                            <button
                              type="button"
                              className="inline-flex min-h-[40px] items-center justify-center rounded-full px-3 text-sm font-semibold text-[var(--danger)] transition-colors hover:bg-red-50"
                              onClick={() => void handleDelete(row)}
                            >
                              Remove
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {filtered.length === 0 && (clients?.length ?? 0) > 0 && (
                <p className="border-t border-[#F0F0F0] px-5 py-6 text-center text-sm text-gray-400">
                  No clients match your search.
                </p>
              )}
            </div>
          )}
        </section>
      )}

      <Modal
        open={addOpen}
        onClose={() => !addBusy && setAddOpen(false)}
        title="Add Client"
        footer={
          <>
            <button
              type="button"
              disabled={addBusy}
              className="inline-flex min-h-[44px] items-center justify-center rounded-full border border-[var(--border)] px-4 text-sm font-medium"
              onClick={() => setAddOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!canSubmitAdd || addBusy}
              className="inline-flex min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white disabled:opacity-40 transition-opacity hover:opacity-90"
              onClick={() => void submitAdd()}
            >
              {addBusy ? "Saving…" : "Add Client"}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          {/* ── Save warning banner (shown after save if GSTIN is Cancelled/Not Found) */}
          {saveWarning && (
            <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
              <span className="mt-0.5 text-base leading-none">⚠️</span>
              <div className="flex-1">
                <p className="text-sm font-semibold text-amber-800">GSTIN Warning</p>
                <p className="mt-0.5 text-xs text-amber-700">{saveWarning}</p>
              </div>
              <div className="flex flex-col gap-2">
                <button
                  type="button"
                  className="inline-flex min-h-[32px] items-center rounded-full bg-amber-700 px-3 text-xs font-semibold text-white hover:bg-amber-800 transition-colors"
                  onClick={() => {
                    setSaveWarning(null);
                    setAddOpen(false);
                    resetAddForm();
                    toast("Client added (with warning)", "success");
                  }}
                >
                  Got it, close
                </button>
              </div>
            </div>
          )}
          <GstinInput value={formGstin} onChange={setFormGstin} id="add-gstin" />

          {/* ── GSTIN Verify button + result chip ──────────────────────── */}
          {gstinOk && (
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                disabled={verifyBusy || !authToken}
                onClick={() => void handleVerifyGstin()}
                className="inline-flex min-h-[36px] items-center gap-1.5 rounded-full bg-[#F5F5F6] px-4 text-xs font-semibold text-[var(--ink)] hover:bg-gray-200/70 disabled:opacity-40 transition-colors"
              >
                {verifyBusy ? (
                  <>
                    <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                    </svg>
                    Verifying…
                  </>
                ) : (
                  <>🔍 Verify GSTIN</>
                )}
              </button>

              {/* Result chip */}
              {verifyResult && (() => {
                const s = verifyResult.status;
                const isActive = verifyResult.valid;
                const isCancelled = s === "Cancelled";
                const isNotFound = s === "Not Found";
                const chip = isActive
                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                  : isCancelled || isNotFound
                    ? "bg-amber-50 text-amber-700 border-amber-200"
                    : "bg-gray-100 text-gray-600 border-gray-200";
                const icon = isActive ? "✓" : isNotFound ? "✗" : "⚠";
                return (
                  <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold ${chip}`}>
                    {icon} {s}
                    {verifyResult.legal_name && (
                      <span className="font-normal opacity-75">· {verifyResult.legal_name}</span>
                    )}
                  </span>
                );
              })()}

              {/* Unavailability notice */}
              {verifyError && (
                <span className="text-xs text-[var(--text-secondary)]">{verifyError}</span>
              )}
            </div>
          )}
          <div>
            <label className="mb-1 block text-sm font-medium">Trade Name</label>
            <input
              value={formTradeName}
              onChange={(e) => setFormTradeName(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-[var(--border)] px-3 text-sm"
              minLength={2}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm font-medium">
                Contact Name
              </label>
              <input
                value={formContactName}
                onChange={(e) => setFormContactName(e.target.value)}
                className="min-h-[44px] w-full rounded-lg border border-[var(--border)] px-3 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">
                Contact Phone
              </label>
              <input
                value={formContactPhone}
                onChange={(e) => setFormContactPhone(e.target.value)}
                className="min-h-[44px] w-full rounded-lg border border-[var(--border)] px-3 text-sm"
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Contact Email
            </label>
            <input
              type="email"
              value={formContactEmail}
              onChange={(e) => setFormContactEmail(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-[var(--border)] px-3 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Assign To</label>
            <select
              value={formAssignedTo}
              onChange={(e) => setFormAssignedTo(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-[var(--border)] px-3 text-sm"
            >
              {assignOptions.map((o) => (
                <option key={o.userId} value={o.userId}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </Modal>

      {connectTarget && (
        <ConnectGstnModal
          open={connectTarget !== null}
          onClose={() => setConnectTarget(null)}
          clientGstinId={connectTarget.id}
          defaultGstin={connectTarget.gstin}
          authToken={authToken ?? ""}
          onSuccess={() => {
            toast("GSTN connected successfully!", "success");
            setConnectTarget(null);
            void mutateClients();
          }}
        />
      )}
    </div>
  );
}
