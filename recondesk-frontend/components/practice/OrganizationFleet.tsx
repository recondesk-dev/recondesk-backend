"use client";

import React, { useState } from "react";
import {
  type PracticeOrganization,
  practiceApi,
} from "@/lib/api";
import {
  Building2,
  Edit2,
  Mail,
  Phone,
  Layers,
  CheckCircle,
  AlertCircle,
  X,
  Plus,
} from "lucide-react";

interface Props {
  organizations: PracticeOrganization[];
  token: string;
  onRefresh: () => void;
}

export function OrganizationFleet({ organizations, token, onRefresh }: Props) {
  const [search, setSearch] = useState("");
  const [editingOrg, setEditingOrg] = useState<PracticeOrganization | null>(null);
  const [legalName, setLegalName] = useState("");
  const [tradeName, setTradeName] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const filtered = organizations.filter((o) => {
    if (!search.trim()) return true;
    const q = search.trim().toLowerCase();
    return (
      o.legal_name.toLowerCase().includes(q) ||
      (o.trade_name && o.trade_name.toLowerCase().includes(q)) ||
      o.pan.toLowerCase().includes(q)
    );
  });

  const startEdit = (org: PracticeOrganization) => {
    setEditingOrg(org);
    setLegalName(org.legal_name || "");
    setTradeName(org.trade_name || "");
    setContactName(org.contact_name || "");
    setContactEmail(org.contact_email || "");
    setContactPhone(org.contact_phone || "");
    setErrorMsg(null);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingOrg) return;
    setIsSaving(true);
    setErrorMsg(null);
    try {
      await practiceApi.updateOrganization(token, editingOrg.id, {
        legal_name: legalName.trim(),
        trade_name: tradeName.trim() || undefined,
        contact_name: contactName.trim() || undefined,
        contact_email: contactEmail.trim() || undefined,
        contact_phone: contactPhone.trim() || undefined,
      });
      setEditingOrg(null);
      onRefresh();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Failed to update organization metadata.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-100 flex items-center gap-2">
            <Building2 className="w-4 h-4 text-cyan-400" />
            PAN-Level Legal Organizations ({organizations.length})
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Groups multi-state GSTINs under legal PAN entities with constitution categorization and contact metadata.
          </p>
        </div>

        <input
          type="text"
          placeholder="Filter by PAN, Legal name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-1.5 text-xs bg-slate-900 border border-slate-800 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 w-64"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.length === 0 ? (
          <div className="col-span-full py-12 text-center text-slate-500 bg-slate-900/60 border border-slate-800 rounded-xl">
            No legal organizations found matching your search.
          </div>
        ) : (
          filtered.map((org) => (
            <div
              key={org.id}
              className="bg-slate-900 border border-slate-800 hover:border-slate-700/80 rounded-xl p-4 transition-all shadow-md flex flex-col justify-between"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <span className="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 inline-block mb-1.5">
                      {org.pan}
                    </span>
                    <h4 className="text-sm font-semibold text-slate-100 truncate" title={org.legal_name}>
                      {org.legal_name}
                    </h4>
                    {org.trade_name && org.trade_name !== org.legal_name ? (
                      <p className="text-xs text-slate-400 truncate mt-0.5">{org.trade_name}</p>
                    ) : null}
                  </div>
                  <button
                    onClick={() => startEdit(org)}
                    className="p-1.5 text-slate-400 hover:text-cyan-400 hover:bg-slate-800 rounded transition-colors shrink-0"
                    title="Edit Metadata"
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="mt-3 pt-3 border-t border-slate-800/80 space-y-1.5 text-xs text-slate-400">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">Constitution:</span>
                    <span className="text-slate-300 font-medium">{org.constitution_of_business || "Other"}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">Linked GSTINs:</span>
                    <span className="text-slate-200 font-semibold">{org.gstin_count || 1} State(s)</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">Open Tasks:</span>
                    <span className="text-amber-400 font-medium">{org.open_task_count || 0}</span>
                  </div>
                </div>

                {(org.contact_email || org.contact_phone) && (
                  <div className="mt-2.5 pt-2 border-t border-slate-800/60 text-[11px] text-slate-400 space-y-1">
                    {org.contact_email && (
                      <div className="flex items-center gap-1.5 truncate">
                        <Mail className="w-3 h-3 text-slate-500 shrink-0" />
                        <span className="truncate">{org.contact_email}</span>
                      </div>
                    )}
                    {org.contact_phone && (
                      <div className="flex items-center gap-1.5">
                        <Phone className="w-3 h-3 text-slate-500 shrink-0" />
                        <span>{org.contact_phone}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="mt-3 pt-2 text-[10px] text-slate-500">
                Created: {new Date(org.created_at).toLocaleDateString()}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Edit Organization Modal */}
      {editingOrg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-5 shadow-2xl animate-in fade-in zoom-in-95">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
              <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
                <Edit2 className="w-4 h-4 text-cyan-400" />
                Edit Legal Organization ({editingOrg.pan})
              </h3>
              <button
                onClick={() => setEditingOrg(null)}
                className="text-slate-400 hover:text-slate-200"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {errorMsg && (
              <div className="mb-4 p-3 bg-rose-500/10 border border-rose-500/30 rounded-lg text-rose-400 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                {errorMsg}
              </div>
            )}

            <form onSubmit={handleSave} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 font-medium mb-1">Legal Name *</label>
                <input
                  type="text"
                  required
                  value={legalName}
                  onChange={(e) => setLegalName(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-medium mb-1">Trade Name</label>
                <input
                  type="text"
                  value={tradeName}
                  onChange={(e) => setTradeName(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-medium mb-1">Contact Name</label>
                <input
                  type="text"
                  value={contactName}
                  onChange={(e) => setContactName(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-300 font-medium mb-1">Email</label>
                  <input
                    type="email"
                    value={contactEmail}
                    onChange={(e) => setContactEmail(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500"
                  />
                </div>
                <div>
                  <label className="block text-slate-300 font-medium mb-1">Phone</label>
                  <input
                    type="text"
                    value={contactPhone}
                    onChange={(e) => setContactPhone(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 focus:outline-none focus:border-cyan-500"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-800 mt-4">
                <button
                  type="button"
                  onClick={() => setEditingOrg(null)}
                  className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 bg-slate-800 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSaving}
                  className="px-4 py-1.5 text-xs font-semibold text-slate-900 bg-cyan-400 hover:bg-cyan-300 rounded-lg transition-colors disabled:opacity-50"
                >
                  {isSaving ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
