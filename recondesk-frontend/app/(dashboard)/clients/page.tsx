"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR, { mutate } from "swr";
import { Users } from "lucide-react";
import {
  addMockClient,
  deleteMockClient,
  mockFetchers,
  updateMockClient,
} from "@/lib/mock-data";
import type { ClientManagementRow } from "@/lib/mock-data";
import type { Client } from "@/lib/types";
import { GstinInput, validateGstin } from "@/components/ui/GstinInput";
import { Modal } from "@/components/ui/Modal";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Avatar } from "@/components/ui/Avatar";

type Reg = Client["registrationType"];

async function invalidateClientsDomain() {
  await Promise.all([
    mutate("/api/clients/management"),
    mutate("/api/clients"),
    mutate((k) => Array.isArray(k) && k[0] === "/api/portfolio"),
    mutate("/api/dashboard/stats"),
    mutate("/api/dashboard/signals"),
    mutate("/api/periods"),
  ]);
}

function useDebounced<T>(value: T, ms: number): T {
  const [d, setD] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setD(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return d;
}

export default function ClientsPage() {
  const { data: rows, error, isLoading } = useSWR("/api/clients/management", mockFetchers["/api/clients/management"]);
  const { data: staff } = useSWR("/api/staff", mockFetchers["/api/staff"]);

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounced(search, 200);
  const [staffFilter, setStaffFilter] = useState<string>("ALL");
  const [pageSize, setPageSize] = useState(10);
  const [page, setPage] = useState(1);

  const [addOpen, setAddOpen] = useState(false);
  const [editRow, setEditRow] = useState<ClientManagementRow | null>(null);
  const [deleteRow, setDeleteRow] = useState<ClientManagementRow | null>(null);
  const [spinners, setSpinners] = useState<Set<string>>(() => new Set());

  const [formGstin, setFormGstin] = useState("");
  const [formName, setFormName] = useState("");
  const [formStaff, setFormStaff] = useState("");
  const [formReg, setFormReg] = useState<Reg>("Regular");

  const filtered = useMemo(() => {
    const list = rows ?? [];
    const q = debouncedSearch.trim().toLowerCase();
    return list.filter((r) => {
      if (staffFilter !== "ALL" && r.client.assignedStaffId !== staffFilter) return false;
      if (!q) return true;
      return (
        r.client.tradeName.toLowerCase().includes(q) ||
        r.client.gstin.toLowerCase().includes(q)
      );
    });
  }, [rows, debouncedSearch, staffFilter]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, staffFilter, pageSize]);

  const totalFiltered = filtered.length;
  const pageCount = Math.max(1, Math.ceil(totalFiltered / pageSize));
  const pageSafe = Math.min(page, pageCount);
  const slice = filtered.slice((pageSafe - 1) * pageSize, pageSafe * pageSize);

  const resetForm = () => {
    setFormGstin("");
    setFormName("");
    setFormStaff(staff?.[0]?.id ?? "");
    setFormReg("Regular");
  };

  useEffect(() => {
    if (addOpen && staff?.length) setFormStaff((s) => s || staff[0].id);
  }, [addOpen, staff]);

  const gstinOk = validateGstin(formGstin).status === "valid";
  const canSubmitAdd =
    gstinOk && formName.trim().length >= 2 && !!formStaff && staff?.some((s) => s.id === formStaff);

  const openAdd = () => {
    resetForm();
    setAddOpen(true);
  };

  const submitAdd = async () => {
    if (!canSubmitAdd) return;
    const id = `client-${Date.now()}`;
    const client: Client = {
      id,
      tradeName: formName.trim(),
      gstin: formGstin.trim().toUpperCase(),
      registrationType: formReg,
      assignedStaffId: formStaff,
      createdAt: new Date().toISOString(),
    };
    addMockClient(client);
    setSpinners((s) => new Set(s).add(id));
    setAddOpen(false);
    resetForm();
    await invalidateClientsDomain();
    setTimeout(() => {
      setSpinners((s) => {
        const n = new Set(s);
        n.delete(id);
        return n;
      });
    }, 500);
  };

  const openEdit = (r: ClientManagementRow) => {
    setEditRow(r);
    setFormName(r.client.tradeName);
    setFormStaff(r.client.assignedStaffId);
    setFormReg(r.client.registrationType);
  };

  const submitEdit = async () => {
    if (!editRow) return;
    if (formName.trim().length < 2 || !formStaff) return;
    updateMockClient(editRow.client.id, {
      tradeName: formName.trim(),
      assignedStaffId: formStaff,
      registrationType: formReg,
    });
    setEditRow(null);
    await invalidateClientsDomain();
  };

  const confirmDelete = async () => {
    if (!deleteRow) return;
    deleteMockClient(deleteRow.client.id);
    setDeleteRow(null);
    await invalidateClientsDomain();
  };

  const finalized = (r: ClientManagementRow) => r.lastRun?.status === "FINALIZED";

  const listLoaded = Array.isArray(rows);
  const hasActiveSearch = debouncedSearch.trim().length > 0;
  const showTableEmptyState =
    !isLoading && !error && listLoaded && totalFiltered === 0;

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={openAdd}
          className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white"
        >
          Add Client
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Could not load data.{" "}
          <button
            type="button"
            className="font-semibold text-[var(--accent)] underline"
            onClick={() => void mutate("/api/clients/management")}
          >
            Retry
          </button>
        </div>
      )}

      {showTableEmptyState ? (
        <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface)] px-6 py-16 text-center">
          <Users
            className="mb-4 h-14 w-14 text-[var(--text-secondary)]"
            strokeWidth={1.25}
            aria-hidden
          />
          {hasActiveSearch ? (
            <>
              <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                No clients found
              </h2>
              <p className="mt-2 max-w-sm text-sm text-[var(--text-secondary)]">
                No clients match your search. Try a different name or GSTIN.
              </p>
            </>
          ) : (rows?.length ?? 0) === 0 ? (
            <>
              <h2 className="text-lg font-semibold text-[var(--text-primary)]">No clients yet</h2>
              <p className="mt-2 max-w-sm text-sm text-[var(--text-secondary)]">
                Add your first client to start reconciling
              </p>
              <button
                type="button"
                onClick={openAdd}
                className="mt-6 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white"
              >
                Add Client
              </button>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                No clients found
              </h2>
              <p className="mt-2 max-w-sm text-sm text-[var(--text-secondary)]">
                No clients match the selected staff filter.
              </p>
            </>
          )}
        </div>
      ) : (
        <>
      <div className="flex flex-wrap items-end gap-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
        <div className="min-w-[200px] flex-1">
          <label className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">Search</label>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
            placeholder="Trade name or GSTIN"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">
            Assigned Staff
          </label>
          <select
            value={staffFilter}
            onChange={(e) => setStaffFilter(e.target.value)}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
          >
            <option value="ALL">All</option>
            {staff?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">
            Rows per page
          </label>
          <select
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
          >
            {[10, 25, 50].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
        <div className="overflow-x-auto">
          <table className="min-w-[900px] w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[#FAFAFB] text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
                <th className="px-4 py-3">Trade Name</th>
                <th className="px-4 py-3">GSTIN</th>
                <th className="px-4 py-3">Registration Type</th>
                <th className="px-4 py-3">Assigned Staff</th>
                <th className="px-4 py-3">Total Runs</th>
                <th className="px-4 py-3">Last Run Date</th>
                <th className="px-4 py-3">Last Status</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => {
                const st = staff?.find((s) => s.id === r.client.assignedStaffId);
                const fin = finalized(r);
                return (
                  <tr key={r.client.id} className="border-b border-[var(--border)]">
                    <td className="px-4 py-3 font-medium text-[var(--text-primary)]">
                      {r.client.tradeName}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{r.client.gstin}</td>
                    <td className="px-4 py-3">{r.client.registrationType}</td>
                    <td className="px-4 py-3">
                      {st && (
                        <div className="flex items-center gap-2">
                          <Avatar initials={st.avatarInitials} size="sm" />
                          <span>{st.name}</span>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono">{r.runCount}</td>
                    <td className="px-4 py-3 text-[var(--text-secondary)]">
                      {r.lastRun
                        ? new Date(r.lastRun.updatedAt).toLocaleDateString("en-IN")
                        : "—"}
                    </td>
                    <td className="px-4 py-3">
                      {r.lastRun ? (
                        <StatusBadge status={r.lastRun.status} finalizedLock={fin} />
                      ) : (
                        <span className="text-[var(--text-secondary)]">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {spinners.has(r.client.id) && (
                          <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-[var(--accent)] border-t-transparent" />
                        )}
                        <button
                          type="button"
                          disabled={fin}
                          title={
                            fin ? "Finalized runs cannot be modified" : "Edit client"
                          }
                          className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--accent-dim)] disabled:cursor-not-allowed disabled:opacity-40"
                          onClick={() => !fin && openEdit(r)}
                        >
                          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                            <path
                              strokeWidth="1.5"
                              d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"
                            />
                          </svg>
                        </button>
                        <button
                          type="button"
                          disabled={fin}
                          title={
                            fin ? "Finalized runs cannot be modified" : "Delete client"
                          }
                          className="rounded p-1 text-[var(--danger)] hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                          onClick={() => !fin && setDeleteRow(r)}
                        >
                          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                            <path
                              strokeWidth="1.5"
                              d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M9 7V5a2 2 0 012-2h2a2 2 0 012 2v2"
                            />
                          </svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border)] px-4 py-3 text-sm text-[var(--text-secondary)]">
          <span>
            Showing {(pageSafe - 1) * pageSize + 1}–{Math.min(pageSafe * pageSize, totalFiltered)} of{" "}
            {totalFiltered}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={pageSafe <= 1}
              className="rounded-lg border border-[var(--border)] px-3 py-1 disabled:opacity-40"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </button>
            <button
              type="button"
              disabled={pageSafe >= pageCount}
              className="rounded-lg border border-[var(--border)] px-3 py-1 disabled:opacity-40"
              onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            >
              Next
            </button>
          </div>
        </div>
      </div>
        </>
      )}

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add Client"
        footer={
          <>
            <button
              type="button"
              onClick={() => setAddOpen(false)}
              className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!canSubmitAdd}
              onClick={() => void submitAdd()}
              className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
            >
              Add Client
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <GstinInput value={formGstin} onChange={setFormGstin} id="add-gstin" />
          <div>
            <label className="mb-1 block text-sm font-medium">Trade Name</label>
            <input
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
              minLength={2}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Assigned Staff</label>
            <select
              value={formStaff}
              onChange={(e) => setFormStaff(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
            >
              {staff?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <span className="mb-2 block text-sm font-medium">Registration Type</span>
            <div className="flex flex-wrap gap-4">
              {(["Regular", "Composition", "SEZ"] as const).map((r) => (
                <label key={r} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="reg"
                    checked={formReg === r}
                    onChange={() => setFormReg(r)}
                  />
                  {r}
                </label>
              ))}
            </div>
          </div>
        </div>
      </Modal>

      <Modal
        open={editRow !== null}
        onClose={() => setEditRow(null)}
        title="Edit Client"
        footer={
          <>
            <button
              type="button"
              onClick={() => setEditRow(null)}
              className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void submitEdit()}
              className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white"
            >
              Save
            </button>
          </>
        }
      >
        {editRow && (
          <div className="space-y-4">
            <p className="font-mono text-sm text-[var(--text-secondary)]">{editRow.client.gstin}</p>
            <div>
              <label className="mb-1 block text-sm font-medium">Trade Name</label>
              <input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Assigned Staff</label>
              <select
                value={formStaff}
                onChange={(e) => setFormStaff(e.target.value)}
                className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
              >
                {staff?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <span className="mb-2 block text-sm font-medium">Registration Type</span>
              <div className="flex flex-wrap gap-4">
                {(["Regular", "Composition", "SEZ"] as const).map((r) => (
                  <label key={r} className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="ereg"
                      checked={formReg === r}
                      onChange={() => setFormReg(r)}
                    />
                    {r}
                  </label>
                ))}
              </div>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={deleteRow !== null}
        onClose={() => setDeleteRow(null)}
        title="Delete client"
        footer={
          <>
            <button
              type="button"
              onClick={() => setDeleteRow(null)}
              className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void confirmDelete()}
              className="rounded-lg bg-[var(--danger)] px-4 py-2 text-sm font-semibold text-white"
            >
              Delete
            </button>
          </>
        }
      >
        {deleteRow && (
          <p className="text-sm text-[var(--text-primary)]">
            Delete <strong>{deleteRow.client.tradeName}</strong>? This cannot be undone.
          </p>
        )}
      </Modal>
    </div>
  );
}
