"use client";

import React, { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import {
  practiceApi,
  type BulkOperationResult,
  type PracticeOrganization,
} from "@/lib/api";
import {
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  Users,
  CheckSquare,
  ListPlus,
  Loader2,
  AlertCircle,
} from "lucide-react";

interface Props {
  open: boolean;
  onClose: () => void;
  token: string;
  organizations: PracticeOrganization[];
  onSuccess?: () => void;
}

export function BulkOperationsModal({
  open,
  onClose,
  token,
  organizations,
  onSuccess,
}: Props) {
  const [activeTab, setActiveTab] = useState<"ASSIGN" | "TASKS">("ASSIGN");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BulkOperationResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Flatten available GSTINs
  const allGstins = organizations.flatMap((org) =>
    (org.gstins || []).map((g) => ({
      ...g,
      orgLegalName: org.legal_name,
      orgPan: org.pan,
    }))
  );

  // State for Bulk Assign
  const [selectedGstinIds, setSelectedGstinIds] = useState<string[]>([]);
  const [assigneeId, setAssigneeId] = useState<string>("");
  const [assignmentRole, setAssignmentRole] = useState<string>("preparer");

  // State for Bulk Tasks
  const [taskTitle, setTaskTitle] = useState<string>("");
  const [taskCategory, setTaskCategory] = useState<string>("GSTR1_FILING");
  const [taskPriority, setTaskPriority] = useState<"LOW" | "MEDIUM" | "HIGH" | "URGENT">("MEDIUM");
  const [taskDueDate, setTaskDueDate] = useState<string>("");
  const [taskPeriod, setTaskPeriod] = useState<string>("");
  const [taskDescription, setTaskDescription] = useState<string>("");

  const handleToggleGstin = (id: string) => {
    setSelectedGstinIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleSelectAllGstins = () => {
    if (selectedGstinIds.length === allGstins.length) {
      setSelectedGstinIds([]);
    } else {
      setSelectedGstinIds(allGstins.map((g) => g.id));
    }
  };

  const resetForm = () => {
    setResult(null);
    setErrorMessage(null);
    setSelectedGstinIds([]);
  };

  const handleBulkAssign = async () => {
    if (!assigneeId.trim()) {
      setErrorMessage("Assignee user ID / name is required.");
      return;
    }
    if (selectedGstinIds.length === 0) {
      setErrorMessage("Please select at least one GSTIN for assignment.");
      return;
    }

    setLoading(true);
    setErrorMessage(null);
    setResult(null);
    try {
      const res = await practiceApi.bulkAssign(token, {
        client_ids: selectedGstinIds,
        assigned_to: assigneeId.trim(),
        assignment_role: assignmentRole,
      });
      setResult(res);
      if (res.succeeded_count > 0 && onSuccess) {
        onSuccess();
      }
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to execute bulk assignment");
    } finally {
      setLoading(false);
    }
  };

  const handleBulkCreateTasks = async () => {
    if (!taskTitle.trim()) {
      setErrorMessage("Task title is required.");
      return;
    }
    if (selectedGstinIds.length === 0) {
      setErrorMessage("Please select at least one GSTIN to attach tasks to.");
      return;
    }

    setLoading(true);
    setErrorMessage(null);
    setResult(null);
    try {
      const tasksPayload = selectedGstinIds.map((gstinId) => {
        const found = allGstins.find((g) => g.id === gstinId);
        return {
          title: taskTitle.trim(),
          category: taskCategory,
          priority: taskPriority,
          client_gstin_id: gstinId,
          period: taskPeriod.trim() || undefined,
          due_date: taskDueDate || undefined,
          description: taskDescription.trim() || undefined,
        };
      });

      const res = await practiceApi.bulkCreateTasks(token, tasksPayload);
      setResult(res);
      if (res.succeeded_count > 0 && onSuccess) {
        onSuccess();
      }
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to generate bulk tasks");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => {
        resetForm();
        onClose();
      }}
      title="CA Practice Bulk Operations"
    >
      <div className="space-y-4 max-h-[75vh] overflow-y-auto pr-1">
        {/* Safety Gate Warning */}
        <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-900 flex items-start gap-2.5">
          <ShieldAlert className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <div className="leading-relaxed">
            <strong className="font-semibold text-amber-950">Statutory Compliance Guardrail:</strong>
            <p className="mt-0.5 text-amber-900/90">
              Bulk operations manage internal staff workflows and tasks. Bulk operations{" "}
              <strong>never bypass</strong> Phase 2 statutory governance checks, Phase 3.2 Maker-Checker
              separation of duties, or Phase 3.3 Client Authorization gates.
            </p>
          </div>
        </div>

        {/* Tab Selection */}
        <div className="flex border-b border-gray-200">
          <button
            type="button"
            onClick={() => {
              setActiveTab("ASSIGN");
              resetForm();
            }}
            className={`pb-2.5 px-4 text-xs font-semibold border-b-2 transition flex items-center gap-1.5 ${
              activeTab === "ASSIGN"
                ? "border-indigo-600 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            Bulk Staff Assignment
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveTab("TASKS");
              resetForm();
            }}
            className={`pb-2.5 px-4 text-xs font-semibold border-b-2 transition flex items-center gap-1.5 ${
              activeTab === "TASKS"
                ? "border-indigo-600 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            <ListPlus className="w-3.5 h-3.5" />
            Bulk Task Generation
          </button>
        </div>

        {/* Error Callout */}
        {errorMessage && (
          <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-700 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Operation Result Report */}
        {result && (
          <div className="p-4 rounded-xl border border-gray-200 bg-gray-50 space-y-3">
            <div className="flex items-center justify-between text-xs font-semibold">
              <span className="text-gray-700">Operation Batch Summary:</span>
              <div className="flex items-center gap-3">
                <span className="text-emerald-600 flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5" /> {result.succeeded_count} Succeeded
                </span>
                {result.failed_count > 0 && (
                  <span className="text-rose-600 flex items-center gap-1">
                    <AlertTriangle className="w-3.5 h-3.5" /> {result.failed_count} Failed
                  </span>
                )}
              </div>
            </div>

            {result.failed_count > 0 && (
              <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 space-y-1">
                <span className="text-[11px] font-bold text-rose-800">Partial Failures:</span>
                <ul className="text-[11px] text-rose-700 list-disc list-inside space-y-0.5">
                  {result.failed.map((f, i) => (
                    <li key={i}>
                      {f.id ? `GSTIN ${f.id}: ` : ""}
                      {f.error}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Target GSTIN Selector */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold text-gray-700">
              Target GSTINs ({selectedGstinIds.length} of {allGstins.length} selected)
            </label>
            <button
              type="button"
              onClick={handleSelectAllGstins}
              className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
            >
              {selectedGstinIds.length === allGstins.length ? "Deselect All" : "Select All"}
            </button>
          </div>

          <div className="max-h-40 overflow-y-auto border border-gray-200 rounded-lg divide-y divide-gray-100 bg-white">
            {allGstins.length === 0 ? (
              <div className="p-4 text-center text-xs text-gray-400">
                No client GSTINs found in current firm.
              </div>
            ) : (
              allGstins.map((g) => (
                <label
                  key={g.id}
                  className="flex items-center gap-3 px-3 py-2 text-xs hover:bg-gray-50 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedGstinIds.includes(g.id)}
                    onChange={() => handleToggleGstin(g.id)}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <div className="flex-1 min-w-0">
                    <span className="font-mono font-semibold text-gray-900">{g.gstin}</span>
                    <span className="text-gray-500 ml-2 truncate">
                      {g.trade_name || g.legal_name || g.orgLegalName}
                    </span>
                  </div>
                  {g.assigned_to && (
                    <span className="text-[10px] text-gray-400">
                      Assigned: {g.assigned_to}
                    </span>
                  )}
                </label>
              ))
            )}
          </div>
        </div>

        {/* Tab 1: Bulk Assign Form */}
        {activeTab === "ASSIGN" && (
          <div className="space-y-3 pt-2 border-t border-gray-100">
            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1">
                Assignee User ID / Name <span className="text-rose-500">*</span>
              </label>
              <input
                type="text"
                value={assigneeId}
                onChange={(e) => setAssigneeId(e.target.value)}
                placeholder="e.g. staff-user-123 or omkar@cadesk.com"
                className="w-full text-xs px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1">
                Assignment Role
              </label>
              <select
                value={assignmentRole}
                onChange={(e) => setAssignmentRole(e.target.value)}
                className="w-full text-xs px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
              >
                <option value="preparer">Preparer (Prepares returns, creates drafts)</option>
                <option value="reviewer">Reviewer (Conducts quality checks)</option>
                <option value="manager">Manager (Maker-Checker Approver)</option>
                <option value="partner">Partner (Full Statutory Authority & Overrides)</option>
              </select>
            </div>

            <div className="pt-3">
              <button
                type="button"
                disabled={loading || selectedGstinIds.length === 0}
                onClick={handleBulkAssign}
                className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-lg bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700 disabled:opacity-50 transition"
              >
                {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Execute Bulk Assignment ({selectedGstinIds.length} GSTINs)
              </button>
            </div>
          </div>
        )}

        {/* Tab 2: Bulk Tasks Form */}
        {activeTab === "TASKS" && (
          <div className="space-y-3 pt-2 border-t border-gray-100">
            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1">
                Task Title Template <span className="text-rose-500">*</span>
              </label>
              <input
                type="text"
                value={taskTitle}
                onChange={(e) => setTaskTitle(e.target.value)}
                placeholder="e.g. Oct 2026 GSTR-1 Reconciliation & Filing Prep"
                className="w-full text-xs px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Category</label>
                <select
                  value={taskCategory}
                  onChange={(e) => setTaskCategory(e.target.value)}
                  className="w-full text-xs px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
                >
                  <option value="GSTR1_FILING">GSTR-1 Filing</option>
                  <option value="GSTR3B_FILING">GSTR-3B Filing</option>
                  <option value="ITC_RECONCILIATION">ITC Reconciliation</option>
                  <option value="ANNUAL_COMPLIANCE">Annual Compliance</option>
                  <option value="AUDIT">Audit / Notice Response</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Priority</label>
                <select
                  value={taskPriority}
                  onChange={(e) => setTaskPriority(e.target.value as any)}
                  className="w-full text-xs px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
                >
                  <option value="LOW">Low</option>
                  <option value="MEDIUM">Medium</option>
                  <option value="HIGH">High</option>
                  <option value="URGENT">Urgent</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Return Period</label>
                <input
                  type="text"
                  value={taskPeriod}
                  onChange={(e) => setTaskPeriod(e.target.value)}
                  placeholder="e.g. 102026"
                  className="w-full text-xs px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Due Date</label>
                <input
                  type="date"
                  value={taskDueDate}
                  onChange={(e) => setTaskDueDate(e.target.value)}
                  className="w-full text-xs px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1">Notes / Instructions</label>
              <textarea
                value={taskDescription}
                onChange={(e) => setTaskDescription(e.target.value)}
                placeholder="Optional work instructions for the assignee..."
                rows={2}
                className="w-full text-xs px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="pt-3">
              <button
                type="button"
                disabled={loading || selectedGstinIds.length === 0}
                onClick={handleBulkCreateTasks}
                className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-lg bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700 disabled:opacity-50 transition"
              >
                {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Generate {selectedGstinIds.length} Practice Tasks
              </button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
