"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

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
  type ClientOrganization,
  type TeamMemberListItem,
} from "@/lib/api";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
  normalizeAuthRole,
  isRoleAdminOrPartner,
  isRoleManagerOrAbove,
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
  const tClients = useTranslations("clients");
  const tCommon = useTranslations("common");
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
  const { data: teamMembers } = useSWR(teamKey, ([, t]) =>
    teamApi.list(t, { includeOwner: true })
  );
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

  const organizationsKey =
    authToken ? (["backend-organizations-list", authToken] as const) : null;
  const {
    data: organizations,
    error: organizationsError,
    isLoading: organizationsLoading,
    mutate: mutateOrganizations,
  } = useSWR(
    organizationsKey,
    ([, t]) => clientsApi.organizations(t),
    { keepPreviousData: true }
  );

  const [viewMode, setViewMode] = useState<"gstin" | "organization">("gstin");
  const [expandedPans, setExpandedPans] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (organizations && organizations.length > 0 && expandedPans.size === 0) {
      setExpandedPans(new Set(organizations.map((o) => o.pan)));
    }
  }, [organizations]);

  const togglePanExpanded = (pan: string) => {
    setExpandedPans((prev) => {
      const next = new Set(prev);
      if (next.has(pan)) {
        next.delete(pan);
      } else {
        next.add(pan);
      }
      return next;
    });
  };

  const roleNorm = normalizeAuthRole(me?.role);
  const canManageAssignments = isRoleManagerOrAbove(roleNorm);
  const canDeleteClient = isRoleAdminOrPartner(roleNorm);
  const isFirmLead = isRoleAdminOrPartner(roleNorm);

  const assigneeNames = useMemo(() => {
    const m = new Map<string, string>();
    if (me?.id) {
      m.set(me.id, me.full_name?.trim() || me.email || "Current User");
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
    const seen = new Set<string>();

    (teamMembers as TeamMemberListItem[] | undefined)?.forEach((tm) => {
      if (tm.status !== "active" || !tm.member_user_id) return;
      if (seen.has(tm.member_user_id)) return;
      seen.add(tm.member_user_id);

      const isOwner =
        (tm.role || "").toLowerCase() === "owner" ||
        (tm.member_user_id === me?.id && isFirmLead);
      const isSelf = tm.member_user_id === me?.id;
      const base = tm.full_name?.trim() || tm.email || "Member";
      const tag = isOwner ? " (Owner)" : isSelf ? " (You)" : "";
      opts.push({
        userId: tm.member_user_id,
        label: `${base}${tag}`,
      });
    });

    if (me?.id && !seen.has(me.id)) {
      seen.add(me.id);
      const tag = isFirmLead ? " (Owner)" : " (You)";
      const base = me.full_name?.trim() || me.email || "Current User";
      opts.push({
        userId: me.id,
        label: `${base}${tag}`,
      });
    }

    return opts;
  }, [me, teamMembers, isFirmLead]);

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounced(search, 200);

  const [addOpen, setAddOpen] = useState(false);
  const [formGstin, setFormGstin] = useState("");
  const [formTradeName, setFormTradeName] = useState("");
  const [formContactName, setFormContactName] = useState("");
  const [formContactEmail, setFormContactEmail] = useState("");
  const [formContactPhone, setFormContactPhone] = useState("");
  const [formAssignedTo, setFormAssignedTo] = useState("");
  const [formSchemeType, setFormSchemeType] = useState<"regular" | "composition" | "casual" | "nrtp" | "isd" | "tds_tcs_deductor">("regular");
  const [formFilingFrequency, setFormFilingFrequency] = useState<"monthly" | "qrmp">("monthly");
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

  const filteredOrganizations = useMemo(() => {
    const list = organizations ?? [];
    const q = debouncedSearch.trim().toLowerCase();
    if (!q) return list;
    return list.filter((o) => {
      const name = (o.company_name ?? "").toLowerCase();
      const legal = (o.legal_name ?? "").toLowerCase();
      const pan = (o.pan ?? "").toLowerCase();
      const childMatch = o.gstins?.some(
        (g) =>
          (g.gstin ?? "").toLowerCase().includes(q) ||
          (g.trade_name ?? "").toLowerCase().includes(q) ||
          (g.state_name ?? "").toLowerCase().includes(q)
      );
      return name.includes(q) || legal.includes(q) || pan.includes(q) || Boolean(childMatch);
    });
  }, [organizations, debouncedSearch]);

  useEffect(() => {
    if (addOpen && !formAssignedTo) {
      if (assignOptions.length) {
        setFormAssignedTo(assignOptions[0]?.userId ?? "");
      } else if (me?.id) {
        setFormAssignedTo(me.id);
      }
    }
  }, [addOpen, assignOptions, formAssignedTo, me?.id]);

  const [connectTarget, setConnectTarget] = useState<{ id: string; gstin: string } | null>(null);


  const gstinOk = validateGstin(formGstin).status === "valid";
  const canSubmitAdd =
    gstinOk &&
    formTradeName.trim().length >= 2 &&
    formContactName.trim().length >= 1 &&
    formContactEmail.includes("@") &&
    formContactPhone.trim().length >= 6;

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
    setFormAssignedTo(assignOptions[0]?.userId ?? me?.id ?? "");
    setFormSchemeType("regular");
    setFormFilingFrequency("monthly");
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
        assigned_to: (formAssignedTo || me?.id || "").trim() || undefined,
        scheme_type: formSchemeType,
        filing_frequency: formFilingFrequency,
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
      void mutateOrganizations();
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
      void mutateOrganizations();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Assignment failed.", "error");
      await mutateClients();
      void mutateOrganizations();
    }
  };

  const handleDelete = async (row: ClientGstin) => {
    if (!authToken || !canDeleteClient) return;
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
      void mutateOrganizations();
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
            {tClients("title")}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {tClients("subtitle")}
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
          {tClients("addClient")}
        </button>
      </div>

      {clientsError && (
        <div className="rounded-[1.25rem] bg-red-50 px-5 py-4 text-sm text-red-800">
          {tClients("couldNotLoad")}{" "}
          <button
            type="button"
            className="font-semibold text-[var(--ink)] underline"
            onClick={() => void mutateClients()}
          >
            {tCommon("retry")}
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
              {tClients("noClients")}
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              {tClients("noClientsSub")}
            </p>
            <button
              type="button"
              className="mt-6 inline-flex min-h-[44px] w-full max-w-xs items-center justify-center rounded-full bg-[var(--ink)] px-5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
              onClick={openAddClient}
            >
              {tClients("addClient")}
            </button>
          </div>
        </div>
      ) : (
        <section className="dashboard-card space-y-5 p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative max-w-md flex-1">
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
                placeholder={
                  viewMode === "organization"
                    ? "Search by company name, PAN, state, or GSTIN..."
                    : tClients("searchPlaceholder")
                }
              />
            </div>

            <div className="inline-flex rounded-full bg-[#F5F5F6] p-1 self-start sm:self-auto">
              <button
                type="button"
                onClick={() => setViewMode("gstin")}
                className={`rounded-full px-4 py-1.5 text-xs font-semibold transition-all ${
                  viewMode === "gstin"
                    ? "bg-white text-[var(--ink)] shadow-sm"
                    : "text-gray-500 hover:text-gray-900"
                }`}
              >
                By GSTIN ({clients?.length ?? 0})
              </button>
              <button
                type="button"
                onClick={() => setViewMode("organization")}
                className={`rounded-full px-4 py-1.5 text-xs font-semibold transition-all ${
                  viewMode === "organization"
                    ? "bg-white text-[var(--ink)] shadow-sm"
                    : "text-gray-500 hover:text-gray-900"
                }`}
              >
                By Company / PAN ({organizations?.length ?? 0})
              </button>
            </div>
          </div>

          {showSkeleton || (viewMode === "organization" && organizationsLoading && !organizations) ? (
            <ClientsSkeleton />
          ) : viewMode === "organization" ? (
            <div className="space-y-4">
              {filteredOrganizations.map((org) => {
                const isExpanded = expandedPans.has(org.pan);
                return (
                  <div
                    key={org.pan}
                    className="overflow-hidden rounded-[1.25rem] border border-[#F0F0F0] bg-white shadow-sm transition-all hover:border-gray-300"
                  >
                    <div className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
                      <div className="space-y-1.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-base font-semibold text-[var(--ink)]">
                            {org.company_name}
                          </h3>
                          <span className="rounded-md bg-gray-100 px-2 py-0.5 font-mono text-xs font-medium text-gray-700">
                            PAN: {org.pan}
                          </span>
                          <span className="rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                            {org.entity_type}
                          </span>
                          {org.requires_dsc ? (
                            <span
                              className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800"
                              title="CGST Rule 26: Corporate entities and LLPs must file GST returns using DSC"
                            >
                              <svg className="h-3 w-3 text-amber-700" fill="currentColor" viewBox="0 0 20 20">
                                <path
                                  fillRule="evenodd"
                                  d="M10 2a4 4 0 00-4 4v2H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-1V6a4 4 0 00-4-4zm2 6V6a2 2 0 10-4 0v2h4z"
                                  clipRule="evenodd"
                                />
                              </svg>
                              DSC Mandatory
                            </span>
                          ) : (
                            <span className="rounded-md border border-gray-200 bg-gray-50 px-2 py-0.5 text-xs text-gray-600">
                              EVC / DSC Allowed
                            </span>
                          )}
                        </div>

                        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                          {org.legal_name && org.legal_name !== org.company_name && (
                            <span>Legal: {org.legal_name} • </span>
                          )}
                          <span>
                            {org.total_gstins} registration{org.total_gstins !== 1 ? "s" : ""} across {org.states.length} state{org.states.length !== 1 ? "s" : ""}
                          </span>
                          <span>•</span>
                          {org.all_connected ? (
                            <span className="font-medium text-emerald-700">All Portals Connected</span>
                          ) : org.connected_count > 0 ? (
                            <span className="font-medium text-amber-700">
                              {org.connected_count}/{org.total_gstins} Portals Connected
                            </span>
                          ) : (
                            <span className="text-gray-400">No GSTN Portals Connected</span>
                          )}
                        </div>

                        <div className="flex flex-wrap gap-1.5 pt-1">
                          {org.states.map((st) => (
                            <span
                              key={st.code}
                              className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-medium text-slate-700"
                            >
                              {st.name} ({st.code})
                            </span>
                          ))}
                        </div>
                      </div>

                      <div className="flex items-center gap-2 pt-2 sm:pt-0">
                        {org.primary_client_id && (
                          <Link
                            href={`/clients/${org.primary_client_id}`}
                            className="inline-flex min-h-[36px] items-center justify-center rounded-full bg-[var(--ink)] px-4 text-xs font-semibold text-white transition-opacity hover:opacity-90"
                          >
                            Open Workspace
                          </Link>
                        )}
                        <button
                          type="button"
                          onClick={() => togglePanExpanded(org.pan)}
                          className="inline-flex min-h-[36px] items-center justify-center rounded-full border border-gray-200 bg-white px-3 text-xs font-semibold text-gray-700 transition-colors hover:bg-gray-50"
                        >
                          {isExpanded ? "Hide GSTINs ▲" : `View GSTINs (${org.total_gstins}) ▼`}
                        </button>
                      </div>
                    </div>

                    {isExpanded && (
                      <div className="border-t border-[#F0F0F0] bg-gray-50/50 p-4">
                        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
                          <table className="w-full text-left text-xs">
                            <thead>
                              <tr className="border-b border-gray-100 bg-gray-50/70 text-[10px] font-medium uppercase tracking-wider text-gray-400">
                                <th className="px-4 py-2.5">State</th>
                                <th className="px-4 py-2.5">GSTIN</th>
                                <th className="px-4 py-2.5">Trade Name</th>
                                <th className="px-4 py-2.5">Filing Frequency</th>
                                <th className="px-4 py-2.5">Assigned To</th>
                                <th className="px-4 py-2.5">GSTN Status</th>
                                <th className="px-4 py-2.5 text-right">Action</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                              {org.gstins.map((g) => (
                                <tr key={g.id} className="hover:bg-gray-50/80">
                                  <td className="px-4 py-2.5 font-medium text-gray-800">
                                    {g.state_name ?? g.state_code ?? "—"}
                                  </td>
                                  <td className="px-4 py-2.5 font-mono font-medium text-gray-600">
                                    {g.gstin}
                                  </td>
                                  <td className="px-4 py-2.5 text-gray-700">
                                    {g.trade_name ?? "—"}
                                  </td>
                                  <td className="px-4 py-2.5 capitalize text-gray-600">
                                    {g.scheme_type ?? "regular"} · {g.filing_frequency ?? "monthly"}
                                  </td>
                                  <td className="px-4 py-2.5 text-gray-600">
                                    {assignLabel(g.assigned_to, assigneeNames)}
                                  </td>
                                  <td className="px-4 py-2.5">
                                    {g.is_gstn_connected ? (
                                      <span className="inline-flex items-center gap-1 font-medium text-emerald-700">
                                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                                        Connected
                                      </span>
                                    ) : (
                                      <span className="text-gray-400">Not Connected</span>
                                    )}
                                  </td>
                                  <td className="px-4 py-2.5 text-right">
                                    <Link
                                      href={`/clients/${g.id}`}
                                      className="font-semibold text-[var(--ink)] hover:underline"
                                    >
                                      Workspace →
                                    </Link>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
              {filteredOrganizations.length === 0 && (organizations?.length ?? 0) > 0 && (
                <p className="border-t border-[#F0F0F0] px-5 py-6 text-center text-sm text-gray-400">
                  No companies match your search.
                </p>
              )}
            </div>
          ) : (
            <div className="overflow-hidden rounded-[1.25rem] ring-1 ring-[#F0F0F0]">
              <div className="overflow-x-auto">
                <table className="min-w-[860px] w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[#F0F0F0] text-[11px] font-medium uppercase tracking-widest text-gray-400">
                      <th className="px-5 py-4">{tClients("tableTradeName")}</th>
                      <th className="px-4 py-4">{tClients("tableGstin")}</th>
                      <th className="px-4 py-4">{tClients("tableAssignTo")}</th>
                      {canDeleteClient && (
                        <th className="px-5 py-4 text-right">{tClients("tableActions")}</th>
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
                          {canManageAssignments ? (
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
                        {canDeleteClient && (
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
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm font-medium">GST Tax Scheme</label>
              <select
                value={formSchemeType}
                onChange={(e) => setFormSchemeType(e.target.value as any)}
                className="min-h-[44px] w-full rounded-lg border border-[var(--border)] px-3 text-sm"
              >
                <option value="regular">Regular</option>
                <option value="composition">Composition Scheme</option>
                <option value="casual">Casual Taxable Person</option>
                <option value="nrtp">Non-Resident (NRTP)</option>
                <option value="isd">Input Service Distributor (ISD)</option>
                <option value="tds_tcs_deductor">TDS / TCS Deductor</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Filing Frequency</label>
              <select
                value={formFilingFrequency}
                onChange={(e) => setFormFilingFrequency(e.target.value as any)}
                className="min-h-[44px] w-full rounded-lg border border-[var(--border)] px-3 text-sm"
              >
                <option value="monthly">Monthly</option>
                <option value="qrmp">QRMP (Quarterly Return Monthly Payment)</option>
              </select>
            </div>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Assign To</label>
            <select
              value={formAssignedTo}
              onChange={(e) => setFormAssignedTo(e.target.value)}
              className="min-h-[44px] w-full rounded-lg border border-[var(--border)] px-3 text-sm"
            >
              {assignOptions.length === 0 && (
                <option value={me?.id ?? ""}>
                  {me?.full_name ? `${me.full_name} (${isFirmLead ? "Owner" : "You"})` : "Assign to me"}
                </option>
              )}
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
