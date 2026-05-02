"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Users } from "lucide-react";

import { Modal } from "@/components/ui/Modal";
import { GstinInput, validateGstin } from "@/components/ui/GstinInput";
import { useToast } from "@/components/providers/ToastProvider";
import {
  authApi,
  clientsApi,
  isApiError,
  teamApi,
  type ClientGstin,
  type TeamMemberListItem,
} from "@/lib/api";
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
    <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="animate-pulse space-y-0">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div
            key={i}
            className="flex gap-4 border-b border-[var(--border)] px-4 py-4 last:border-b-0"
          >
            <div className="h-4 flex-1 rounded bg-[var(--border)]" />
            <div className="h-4 w-40 rounded bg-[var(--border)]" />
            <div className="h-10 w-44 rounded bg-[var(--border)]" />
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

export default function ClientsPage() {
  const toast = useToast();
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.length > 0
      ? tokenState
      : null;

  const meKey = authToken ? (["clients-me", authToken] as const) : null;
  const teamKey = authToken ? (["clients-team", authToken] as const) : null;
  const clientsKey =
    authToken ? ([CLIENTS_KEY, authToken] as const) : null;

  const { data: me } = useSWR(meKey, ([, t]) => authApi.me(t));
  const { data: teamMembers } = useSWR(teamKey, ([, t]) => teamApi.list(t));
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

  const roleNorm = (me?.role ?? "staff").toLowerCase();
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

  const gstinOk = validateGstin(formGstin).status === "valid";
  const canSubmitAdd =
    gstinOk &&
    formTradeName.trim().length >= 2 &&
    formContactName.trim().length >= 1 &&
    formContactEmail.includes("@") &&
    formContactPhone.trim().length >= 6 &&
    !!formAssignedTo;

  const resetAddForm = () => {
    setFormGstin("");
    setFormTradeName("");
    setFormContactName("");
    setFormContactEmail("");
    setFormContactPhone("");
    setFormAssignedTo(assignOptions[0]?.userId ?? "");
  };

  const submitAdd = async () => {
    if (!authToken || !canSubmitAdd) return;
    setAddBusy(true);
    try {
      await clientsApi.create(authToken, {
        gstin: formGstin.trim().toUpperCase(),
        trade_name: formTradeName.trim(),
        contact_name: formContactName.trim(),
        contact_email: formContactEmail.trim(),
        contact_phone: formContactPhone.trim(),
        assigned_to: formAssignedTo || undefined,
      });
      toast("Client added", "success");
      setAddOpen(false);
      resetAddForm();
      await mutateClients();
    } catch (e: unknown) {
      toast(isApiError(e) ? e.detail : "Could not add client.", "error");
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
      <div className="flex flex-wrap justify-end gap-3">
        <button
          type="button"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg bg-[var(--accent)] px-5 text-sm font-semibold text-white"
          onClick={() => {
            resetAddForm();
            setAddOpen(true);
          }}
        >
          Add Client
        </button>
      </div>

      {clientsError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Could not load clients.{" "}
          <button
            type="button"
            className="font-semibold text-[var(--accent)] underline"
            onClick={() => void mutateClients()}
          >
            Retry
          </button>
        </div>
      )}

      {!authToken && tokenState === false && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          Sign in to load clients from your workspace.
        </div>
      )}

      {showEmpty ? (
        <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface)] px-6 py-16 text-center">
          <Users
            className="mb-4 h-14 w-14 text-[var(--text-secondary)]"
            strokeWidth={1.25}
            aria-hidden
          />
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">
            No clients yet
          </h2>
          <p className="mt-2 max-w-sm text-sm text-[var(--text-secondary)]">
            Add your first client to start reconciling.
          </p>
          <button
            type="button"
            className="mt-6 inline-flex min-h-[44px] items-center justify-center rounded-lg bg-[var(--accent)] px-5 text-sm font-semibold text-white"
            onClick={() => {
              resetAddForm();
              setAddOpen(true);
            }}
          >
            Add Client
          </button>
        </div>
      ) : (
        <>
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <label className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">
              Search
            </label>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="min-h-[44px] w-full max-w-md rounded-lg border border-[var(--border)] px-3 text-sm"
              placeholder="Trade name or GSTIN"
            />
          </div>

          {showSkeleton ? (
            <ClientsSkeleton />
          ) : (
            <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
              <div className="overflow-x-auto">
                <table className="min-w-[860px] w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border)] bg-[#FAFAFB] text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                      <th className="px-4 py-3">Trade Name</th>
                      <th className="px-4 py-3">GSTIN</th>
                      <th className="px-4 py-3">Assign To</th>
                      {isAdmin && (
                        <th className="px-4 py-3 text-right">Actions</th>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((row) => (
                      <tr
                        key={row.id}
                        className="border-b border-[var(--border)] last:border-b-0"
                      >
                        <td className="px-4 py-3 font-medium text-[var(--text-primary)]">
                          {row.trade_name ?? "—"}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs">
                          {row.gstin}
                        </td>
                        <td className="px-4 py-3">
                          {isAdmin ? (
                            <select
                              className="min-h-[44px] w-full max-w-[260px] rounded-lg border border-[var(--border)] bg-white px-3 text-sm"
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
                            <span className="text-[var(--text-secondary)]">
                              {assignLabel(row.assigned_to, assigneeNames)}
                            </span>
                          )}
                        </td>
                        {isAdmin && (
                          <td className="px-4 py-3 text-right">
                            <button
                              type="button"
                              className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg px-3 text-sm font-semibold text-[var(--danger)] hover:bg-red-50"
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
                <p className="border-t border-[var(--border)] px-4 py-6 text-center text-sm text-[var(--text-secondary)]">
                  No clients match your search.
                </p>
              )}
            </div>
          )}
        </>
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
              className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-[var(--border)] px-4 text-sm font-medium"
              onClick={() => setAddOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!canSubmitAdd || addBusy}
              className="inline-flex min-h-[44px] items-center justify-center rounded-lg bg-[var(--accent)] px-5 text-sm font-semibold text-white disabled:opacity-40"
              onClick={() => void submitAdd()}
            >
              {addBusy ? "Saving…" : "Add Client"}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <GstinInput value={formGstin} onChange={setFormGstin} id="add-gstin" />
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
    </div>
  );
}
