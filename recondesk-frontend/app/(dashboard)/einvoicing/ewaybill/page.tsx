"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Truck,
  FileText,
  Download,
  Plus,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Clock,
  Ban,
  ArrowRight,
  ExternalLink,
  ChevronRight,
  ShieldCheck,
  Building2,
  MapPin,
  X,
} from "lucide-react";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { clientsApi, ClientGstin, ewaybillApi, EwayBillRecord, EwayBillCreateInput } from "@/lib/api";

function EwayBillWorkbenchContent() {
  const token = useAccessToken();
  const searchParams = useSearchParams();
  const initialClientId = searchParams?.get("client_id") || "";

  const [clients, setClients] = useState<ClientGstin[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>(initialClientId);
  const [records, setRecords] = useState<EwayBillRecord[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Modals state
  const [isCreateModalOpen, setIsCreateModalOpen] = useState<boolean>(false);
  const [isUpdateVehicleOpen, setIsUpdateVehicleOpen] = useState<boolean>(false);
  const [isCancelModalOpen, setIsCancelModalOpen] = useState<boolean>(false);
  const [selectedEwb, setSelectedEwb] = useState<EwayBillRecord | null>(null);

  // Update vehicle form
  const [updateVehicleNo, setUpdateVehicleNo] = useState<string>("");
  const [updateFromPlace, setUpdateFromPlace] = useState<string>("");
  const [updateReasonCode, setUpdateReasonCode] = useState<string>("2");
  const [updateRemark, setUpdateRemark] = useState<string>("");

  // Cancel form
  const [cancelReasonCode, setCancelReasonCode] = useState<string>("2");
  const [cancelRemarks, setCancelRemarks] = useState<string>("");

  // Standalone create form
  const [createDocType, setCreateDocType] = useState<string>("INV");
  const [createDocNo, setCreateDocNo] = useState<string>("");
  const [createDocDate, setCreateDocDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [createFromGstin, setCreateFromGstin] = useState<string>("");
  const [createFromTrdName, setCreateFromTrdName] = useState<string>("");
  const [createFromAddr, setCreateFromAddr] = useState<string>("");
  const [createFromPlace, setCreateFromPlace] = useState<string>("");
  const [createFromPin, setCreateFromPin] = useState<string>("400001");
  const [createFromState, setCreateFromState] = useState<string>("27");
  const [createToGstin, setCreateToGstin] = useState<string>("URP");
  const [createToTrdName, setCreateToTrdName] = useState<string>("");
  const [createToAddr, setCreateToAddr] = useState<string>("");
  const [createToPlace, setCreateToPlace] = useState<string>("");
  const [createToPin, setCreateToPin] = useState<string>("560001");
  const [createToState, setCreateToState] = useState<string>("29");
  const [createDistance, setCreateDistance] = useState<string>("250");
  const [createVehicleNo, setCreateVehicleNo] = useState<string>("");
  const [createTransMode, setCreateTransMode] = useState<string>("1");
  const [createTransId, setCreateTransId] = useState<string>("");
  const [createItemDesc, setCreateItemDesc] = useState<string>("Goods");
  const [createItemHsn, setCreateItemHsn] = useState<string>("8471");
  const [createItemQty, setCreateItemQty] = useState<string>("1");
  const [createItemValue, setCreateItemValue] = useState<string>("50000");

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  useEffect(() => {
    async function loadClients() {
      if (!token) return;
      try {
        const clientList = await clientsApi.list(token);
        setClients(clientList);
        if (!selectedClientId && clientList.length > 0) {
          setSelectedClientId(clientList[0].id);
        }
      } catch (err: any) {
        console.error("Failed to load clients:", err);
      }
    }
    loadClients();
  }, [token]);

  useEffect(() => {
    const sel = clients.find((c) => c.id === selectedClientId);
    if (sel) {
      if (!createFromGstin) setCreateFromGstin(sel.gstin);
      if (!createFromTrdName) setCreateFromTrdName(sel.trade_name || sel.legal_name || "");
      if (sel.gstin && sel.gstin.length >= 2) {
        const sc = sel.gstin.substring(0, 2);
        if (/^\d{2}$/.test(sc)) {
          setCreateFromState(sc);
        }
      }
    }
  }, [selectedClientId, clients, createFromGstin, createFromTrdName]);

  useEffect(() => {
    async function loadEwayBills() {
      if (!token || !selectedClientId) return;
      setIsLoading(true);
      setError(null);
      try {
        const data = await ewaybillApi.list(token, selectedClientId, statusFilter || undefined);
        setRecords(data);
      } catch (err: any) {
        setError(err.message || "Failed to load E-Way Bills");
      } finally {
        setIsLoading(false);
      }
    }
    loadEwayBills();
  }, [token, selectedClientId, statusFilter]);

  const activeCount = records.filter((r) => r.status === "ACTIVE").length;
  const partACount = records.filter((r) => r.status === "PART_A_ONLY").length;
  const cancelledCount = records.filter((r) => r.status === "CANCELLED").length;

  const handleUpdateVehicle = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !selectedEwb) return;
    setIsSubmitting(true);
    try {
      await ewaybillApi.updateVehicle(token, selectedEwb.id, {
        ewb_number: selectedEwb.ewb_number,
        vehicle_no: updateVehicleNo,
        from_place: updateFromPlace || selectedEwb.from_place,
        from_state_code: selectedEwb.from_state_code,
        reason_code: updateReasonCode,
        reason_remark: updateRemark,
        trans_mode: "1",
      });
      setIsUpdateVehicleOpen(false);
      // reload
      const data = await ewaybillApi.list(token, selectedClientId, statusFilter || undefined);
      setRecords(data);
    } catch (err: any) {
      alert("Failed to update vehicle: " + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancelEwb = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !selectedEwb) return;
    setIsSubmitting(true);
    try {
      await ewaybillApi.cancel(token, selectedEwb.id, {
        ewb_number: selectedEwb.ewb_number,
        cancel_reason_code: cancelReasonCode,
        cancel_remarks: cancelRemarks,
      });
      setIsCancelModalOpen(false);
      // reload
      const data = await ewaybillApi.list(token, selectedClientId, statusFilter || undefined);
      setRecords(data);
    } catch (err: any) {
      alert("Failed to cancel E-Way Bill: " + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCreateStandalone = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !selectedClientId) return;
    setIsSubmitting(true);
    try {
      const taxable = parseFloat(createItemValue) || 0;
      const igst = Math.round(taxable * 0.18);
      const totalVal = taxable + igst;

      const payload: EwayBillCreateInput = {
        client_gstin_id: selectedClientId,
        supply_type: "O",
        sub_supply_type: "1",
        doc_type: createDocType,
        doc_number: createDocNo,
        doc_date: createDocDate,
        from_gstin: createFromGstin || "27AABCR1234F1Z5",
        from_trade_name: createFromTrdName || "Supplier Company",
        from_addr1: createFromAddr || "101 Industrial Estate",
        from_place: createFromPlace || "Mumbai",
        from_pincode: parseInt(createFromPin, 10) || 400001,
        from_state_code: createFromState || "27",
        to_gstin: createToGstin || "URP",
        to_trade_name: createToTrdName || "Consignee Trader",
        to_addr1: createToAddr || "Plot 42 Logistics Hub",
        to_place: createToPlace || "Bengaluru",
        to_pincode: parseInt(createToPin, 10) || 560001,
        to_state_code: createToState || "29",
        total_taxable_value: taxable,
        cgst_amount: 0,
        sgst_amount: 0,
        igst_amount: igst,
        cess_amount: 0,
        total_invoice_value: totalVal,
        items: [
          {
            item_name: createItemDesc,
            hsn_code: createItemHsn,
            quantity: parseFloat(createItemQty) || 1,
            unit: "NOS",
            taxable_value: taxable,
            igst_rate: 18,
            igst_amount: igst,
          },
        ],
        transporter_id: createTransId || undefined,
        trans_mode: createTransMode,
        distance_km: parseInt(createDistance, 10) || 250,
        vehicle_no: createVehicleNo || undefined,
        vehicle_type: "R",
      };

      await ewaybillApi.generate(token, payload);
      setIsCreateModalOpen(false);
      // reload
      const data = await ewaybillApi.list(token, selectedClientId, statusFilter || undefined);
      setRecords(data);
    } catch (err: any) {
      alert("Failed to generate E-Way Bill: " + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDownloadBulkJson = async () => {
    if (!token || !selectedClientId) return;
    try {
      const blob = await ewaybillApi.downloadBulkJson(token, selectedClientId, statusFilter || undefined);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const client = clients.find((c) => c.id === selectedClientId);
      const gstinTag = client?.gstin ? `_${client.gstin}` : "";
      a.download = `EWAYBILL_BULK${gstinTag}_${records.length}_RECORDS.json`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: any) {
      alert("Failed to download NIC Bulk JSON: " + (err.message || err));
    }
  };

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-6 py-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b pb-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-500/10 px-2.5 py-0.5 text-xs font-semibold text-blue-600">
              <Truck className="h-3.5 w-3.5" />
              Logistics & Transportation
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-600">
              <ShieldCheck className="h-3 w-3" />
              NIC Schema V1.04
            </span>
          </div>
          <h1 className="mt-2 text-2xl font-bold tracking-tight text-[var(--ink)] sm:text-3xl">
            E-Way Bill Generation & Management Suite
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Generate Part A & Part B slips, update vehicles, cancel within 24 hours, and export official NIC Bulk JSON for direct upload on{" "}
            <a href="https://ewaybillgst.gov.in" target="_blank" rel="noreferrer" className="text-blue-600 underline">
              ewaybillgst.gov.in
            </a>.
          </p>
        </div>

        {/* Client selector & primary actions */}
        <div className="flex flex-wrap items-center gap-3">
          {clients.length > 0 && (
            <select
              value={selectedClientId}
              onChange={(e) => setSelectedClientId(e.target.value)}
              className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none"
            >
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.trade_name || c.gstin} ({c.gstin})
                </option>
              ))}
            </select>
          )}

          <button
            onClick={handleDownloadBulkJson}
            title="Download Government NIC Bulk JSON export"
            className="inline-flex items-center gap-2 rounded-xl border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 transition-colors"
          >
            <Download className="h-4 w-4 text-gray-500" />
            Export NIC JSON
          </button>

          <button
            onClick={() => setIsCreateModalOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white shadow-sm hover:opacity-90 transition-opacity"
          >
            <Plus className="h-4 w-4" />
            New E-Way Bill
          </button>
        </div>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-gray-400">Total Consignments</span>
            <FileText className="h-5 w-5 text-gray-400" />
          </div>
          <p className="mt-3 text-3xl font-bold text-[var(--ink)]">{records.length}</p>
          <p className="mt-1 text-xs text-gray-500">Tracked in this tax entity</p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-gray-400">Active (In Transit)</span>
            <Truck className="h-5 w-5 text-emerald-500" />
          </div>
          <p className="mt-3 text-3xl font-bold text-emerald-600">{activeCount}</p>
          <p className="mt-1 text-xs text-gray-500">Part A & B valid on road</p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-gray-400">Part A Only</span>
            <Clock className="h-5 w-5 text-amber-500" />
          </div>
          <p className="mt-3 text-3xl font-bold text-amber-600">{partACount}</p>
          <p className="mt-1 text-xs text-gray-500">Awaiting transporter/vehicle</p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-gray-400">Cancelled</span>
            <Ban className="h-5 w-5 text-red-500" />
          </div>
          <p className="mt-3 text-3xl font-bold text-red-600">{cancelledCount}</p>
          <p className="mt-1 text-xs text-gray-500">Cancelled within 24h</p>
        </div>
      </div>

      {/* Filter Tabs & Data Table */}
      <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div className="flex items-center gap-2">
            {[
              { label: "All Consignments", value: "" },
              { label: "Active", value: "ACTIVE" },
              { label: "Part A Only", value: "PART_A_ONLY" },
              { label: "Cancelled", value: "CANCELLED" },
            ].map((tab) => (
              <button
                key={tab.value}
                onClick={() => setStatusFilter(tab.value)}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                  statusFilter === tab.value ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-100"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <span className="text-xs text-gray-400">{records.length} records found</span>
        </div>

        {isLoading ? (
          <div className="py-20 text-center">
            <RefreshCw className="mx-auto h-8 w-8 animate-spin text-gray-400" />
            <p className="mt-3 text-sm text-gray-500">Loading E-Way Bills...</p>
          </div>
        ) : error ? (
          <div className="p-8 text-center text-red-600">
            <AlertCircle className="mx-auto h-8 w-8" />
            <p className="mt-2 text-sm font-semibold">{error}</p>
          </div>
        ) : records.length === 0 ? (
          <div className="py-20 text-center">
            <Truck className="mx-auto h-12 w-12 text-gray-300" />
            <h3 className="mt-3 text-base font-semibold text-gray-900">No E-Way Bills Found</h3>
            <p className="mt-1 text-sm text-gray-500 max-w-sm mx-auto">
              Generate your first E-Way Bill standalone or create one directly from an invoice in the E-Invoicing workbench.
            </p>
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="mt-4 inline-flex items-center gap-2 rounded-xl bg-[var(--ink)] px-4 py-2 text-xs font-semibold text-white shadow-sm"
            >
              <Plus className="h-3.5 w-3.5" />
              Generate First E-Way Bill
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b bg-gray-50 text-xs font-semibold uppercase tracking-wider text-gray-500">
                  <th className="px-6 py-3.5">E-Way Bill No.</th>
                  <th className="px-6 py-3.5">Document</th>
                  <th className="px-6 py-3.5">From &rarr; To</th>
                  <th className="px-6 py-3.5">Vehicle / Mode</th>
                  <th className="px-6 py-3.5">Invoice Value</th>
                  <th className="px-6 py-3.5">Validity</th>
                  <th className="px-6 py-3.5">Status</th>
                  <th className="px-6 py-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {records.map((r) => (
                  <tr key={r.id} className="hover:bg-gray-50/70 transition-colors">
                    <td className="px-6 py-4 font-mono font-medium text-blue-600">
                      {r.ewb_number}
                      <span className="block text-[11px] font-normal text-gray-400 font-sans">
                        {new Date(r.ewb_date).toLocaleDateString()}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="font-semibold text-gray-900">{r.doc_number}</span>
                      <span className="block text-xs text-gray-500">
                        {r.doc_type} &bull; {r.doc_date}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-xs">
                        <span className="font-medium text-gray-800">{r.from_trade_name}</span> ({r.from_place})
                        <span className="block text-gray-400">&darr;</span>
                        <span className="font-medium text-gray-800">{r.to_trade_name}</span> ({r.to_place})
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      {r.vehicle_no ? (
                        <div>
                          <span className="inline-flex items-center gap-1 rounded bg-gray-100 px-2 py-0.5 font-mono text-xs font-semibold text-gray-800">
                            {r.vehicle_no}
                          </span>
                          <span className="block text-[11px] text-gray-400 mt-0.5">
                            {r.distance_km} KM &bull; Road
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs italic text-amber-600">Pending Part B</span>
                      )}
                    </td>
                    <td className="px-6 py-4 font-mono font-semibold text-gray-900">
                      ₹{r.total_invoice_value.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                    </td>
                    <td className="px-6 py-4 text-xs text-gray-500">
                      {r.valid_until ? (
                        <div>
                          <span>{new Date(r.valid_until).toLocaleDateString()}</span>
                          <span className="block text-[11px] text-gray-400">
                            {new Date(r.valid_until).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                          </span>
                        </div>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                          r.status === "ACTIVE"
                            ? "bg-emerald-500/10 text-emerald-600"
                            : r.status === "PART_A_ONLY"
                            ? "bg-amber-500/10 text-amber-600"
                            : "bg-red-500/10 text-red-600"
                        }`}
                      >
                        {r.status === "ACTIVE" && <CheckCircle2 className="h-3 w-3" />}
                        {r.status === "PART_A_ONLY" && <Clock className="h-3 w-3" />}
                        {r.status === "CANCELLED" && <Ban className="h-3 w-3" />}
                        {r.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right">
                      {r.status !== "CANCELLED" && (
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => {
                              setSelectedEwb(r);
                              setUpdateVehicleNo(r.vehicle_no || "");
                              setUpdateFromPlace(r.from_place || "");
                              setIsUpdateVehicleOpen(true);
                            }}
                            className="rounded-lg border border-gray-200 bg-white px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-50 transition-colors"
                          >
                            Update Part B
                          </button>
                          <button
                            onClick={() => {
                              setSelectedEwb(r);
                              setIsCancelModalOpen(true);
                            }}
                            className="rounded-lg border border-red-200 bg-white px-2 py-1 text-xs font-semibold text-red-600 hover:bg-red-50 transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* MODAL 1: Update Vehicle */}
      {isUpdateVehicleOpen && selectedEwb && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-xs p-4 sm:p-6"
          role="dialog"
          aria-modal="true"
        >
          <div className="flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-2xl bg-white shadow-2xl border border-gray-100">
            <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4 shrink-0 bg-white">
              <h3 className="text-lg font-bold text-gray-900">Update Vehicle (Part B)</h3>
              <button
                type="button"
                onClick={() => setIsUpdateVehicleOpen(false)}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
                aria-label="Close"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleUpdateVehicle} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 overflow-y-auto p-6 space-y-4">
                <div>
                  <label className="text-xs font-semibold text-gray-700">E-Way Bill Number</label>
                  <input
                    type="text"
                    disabled
                    value={selectedEwb.ewb_number}
                    className="mt-1 w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-600"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-700">New Vehicle Number *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. MH12AB1234"
                    value={updateVehicleNo}
                    onChange={(e) => setUpdateVehicleNo(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-700">Place of Transshipment / Update *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Pune Hub"
                    value={updateFromPlace}
                    onChange={(e) => setUpdateFromPlace(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-700">Reason for Vehicle Change</label>
                  <select
                    value={updateReasonCode}
                    onChange={(e) => setUpdateReasonCode(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  >
                    <option value="1">1 - Vehicle Breakdown</option>
                    <option value="2">2 - Transshipment</option>
                    <option value="3">3 - Others</option>
                    <option value="4">4 - First Time Vehicle Update</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-700">Remarks (Optional)</label>
                  <input
                    type="text"
                    placeholder="e.g. Transferred goods to secondary fleet"
                    value={updateRemark}
                    onChange={(e) => setUpdateRemark(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
              </div>
              <div className="flex justify-end gap-3 border-t border-gray-100 bg-gray-50/70 px-6 py-4 shrink-0 rounded-b-2xl">
                <button
                  type="button"
                  onClick={() => setIsUpdateVehicleOpen(false)}
                  className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50 shadow-xs"
                >
                  Close
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="rounded-xl bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {isSubmitting ? "Updating..." : "Save Vehicle Update"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 2: Cancel E-Way Bill */}
      {isCancelModalOpen && selectedEwb && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-xs p-4 sm:p-6"
          role="dialog"
          aria-modal="true"
        >
          <div className="flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-2xl bg-white shadow-2xl border border-gray-100">
            <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4 shrink-0 bg-white">
              <h3 className="text-lg font-bold text-red-600">Cancel E-Way Bill (24h Window)</h3>
              <button
                type="button"
                onClick={() => setIsCancelModalOpen(false)}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
                aria-label="Close"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleCancelEwb} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 overflow-y-auto p-6 space-y-4">
                <p className="text-xs text-gray-500">
                  Under statutory Rule 138(9), an E-Way Bill can only be cancelled within 24 hours of generation if the goods are not in transit.
                </p>
                <div>
                  <label className="text-xs font-semibold text-gray-700">Reason for Cancellation</label>
                  <select
                    value={cancelReasonCode}
                    onChange={(e) => setCancelReasonCode(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm focus:border-red-500 focus:outline-none"
                  >
                    <option value="1">1 - Duplicate Consignment</option>
                    <option value="2">2 - Order Cancelled by Buyer</option>
                    <option value="3">3 - Data Entry Mistake</option>
                    <option value="4">4 - Others</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-700">Cancellation Remarks *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Order cancelled prior to dispatch"
                    value={cancelRemarks}
                    onChange={(e) => setCancelRemarks(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm focus:border-red-500 focus:outline-none"
                  />
                </div>
              </div>
              <div className="flex justify-end gap-3 border-t border-gray-100 bg-gray-50/70 px-6 py-4 shrink-0 rounded-b-2xl">
                <button
                  type="button"
                  onClick={() => setIsCancelModalOpen(false)}
                  className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50 shadow-xs"
                >
                  Back
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="rounded-xl bg-red-600 px-4 py-2 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
                >
                  {isSubmitting ? "Cancelling..." : "Confirm Cancellation"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 3: Standalone E-Way Bill Generation */}
      {isCreateModalOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-xs p-4 sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-labelledby="new-ewaybill-modal-title"
        >
          <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl border border-gray-100">
            <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4 shrink-0 bg-white">
              <div>
                <h3 id="new-ewaybill-modal-title" className="text-lg font-bold text-gray-900">
                  New Standalone E-Way Bill
                </h3>
                <p className="text-xs text-gray-500">
                  Generates Part A & Part B conforming to Government NIC Schema V1.04.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateModalOpen(false)}
                className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
                aria-label="Close"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleCreateStandalone} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5 space-y-6">
                {/* Document details */}
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-gray-400">1. Document Details</h4>
                  <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div>
                      <label className="text-xs font-semibold text-gray-700">Document Type</label>
                      <select
                        value={createDocType}
                        onChange={(e) => setCreateDocType(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm"
                      >
                        <option value="INV">Tax Invoice</option>
                        <option value="BIL">Bill of Supply</option>
                        <option value="CHL">Delivery Challan</option>
                        <option value="CNT">Credit Note</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-gray-700">Document No. *</label>
                      <input
                        type="text"
                        required
                        placeholder="e.g. INV/2026/001"
                        value={createDocNo}
                        onChange={(e) => setCreateDocNo(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-gray-700">Document Date *</label>
                      <input
                        type="date"
                        required
                        value={createDocDate}
                        onChange={(e) => setCreateDocDate(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm"
                      />
                    </div>
                  </div>
                </div>

                {/* From & To */}
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-gray-400">2. Consignor & Consignee</h4>
                  <div className="mt-2 grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div className="rounded-xl border border-gray-100 bg-gray-50/50 p-3 space-y-2">
                      <span className="text-xs font-bold text-gray-700">Consignor (Dispatch From)</span>
                      <input
                        type="text"
                        placeholder="From GSTIN (15 chars)"
                        value={createFromGstin}
                        onChange={(e) => setCreateFromGstin(e.target.value)}
                        className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                      />
                      <input
                        type="text"
                        placeholder="Trade Name / Legal Name"
                        value={createFromTrdName}
                        onChange={(e) => setCreateFromTrdName(e.target.value)}
                        className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                      />
                      <div className="grid grid-cols-2 gap-2">
                        <input
                          type="text"
                          placeholder="City"
                          value={createFromPlace}
                          onChange={(e) => setCreateFromPlace(e.target.value)}
                          className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                        />
                        <input
                          type="text"
                          placeholder="PIN Code"
                          value={createFromPin}
                          onChange={(e) => setCreateFromPin(e.target.value)}
                          className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                        />
                      </div>
                    </div>

                    <div className="rounded-xl border border-gray-100 bg-gray-50/50 p-3 space-y-2">
                      <span className="text-xs font-bold text-gray-700">Consignee (Bill/Ship To)</span>
                      <input
                        type="text"
                        placeholder="To GSTIN (or URP for unregistered)"
                        value={createToGstin}
                        onChange={(e) => setCreateToGstin(e.target.value)}
                        className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                      />
                      <input
                        type="text"
                        placeholder="Buyer Trade Name"
                        value={createToTrdName}
                        onChange={(e) => setCreateToTrdName(e.target.value)}
                        className="w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                      />
                      <div className="grid grid-cols-2 gap-2">
                        <input
                          type="text"
                          placeholder="Destination City"
                          value={createToPlace}
                          onChange={(e) => setCreateToPlace(e.target.value)}
                          className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                        />
                        <input
                          type="text"
                          placeholder="Destination PIN"
                          value={createToPin}
                          onChange={(e) => setCreateToPin(e.target.value)}
                          className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Items & Values */}
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-gray-400">3. Goods & Financials</h4>
                  <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <div>
                      <label className="text-[11px] font-semibold text-gray-600">Product Desc</label>
                      <input
                        type="text"
                        value={createItemDesc}
                        onChange={(e) => setCreateItemDesc(e.target.value)}
                        className="mt-1 w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-semibold text-gray-600">HSN Code</label>
                      <input
                        type="text"
                        value={createItemHsn}
                        onChange={(e) => setCreateItemHsn(e.target.value)}
                        className="mt-1 w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-semibold text-gray-600">Quantity</label>
                      <input
                        type="number"
                        value={createItemQty}
                        onChange={(e) => setCreateItemQty(e.target.value)}
                        className="mt-1 w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-semibold text-gray-600">Taxable Value (₹)</label>
                      <input
                        type="number"
                        value={createItemValue}
                        onChange={(e) => setCreateItemValue(e.target.value)}
                        className="mt-1 w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-semibold"
                      />
                    </div>
                  </div>
                </div>

                {/* Part B Transport */}
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-gray-400">4. Part B Transport Details</h4>
                  <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div>
                      <label className="text-xs font-semibold text-gray-700">Approx Distance (KM) *</label>
                      <input
                        type="number"
                        required
                        placeholder="e.g. 250"
                        value={createDistance}
                        onChange={(e) => setCreateDistance(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-gray-700">Vehicle Number</label>
                      <input
                        type="text"
                        placeholder="e.g. MH12AB1234"
                        value={createVehicleNo}
                        onChange={(e) => setCreateVehicleNo(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-gray-700">Transporter ID (Optional)</label>
                      <input
                        type="text"
                        placeholder="Transporter GSTIN"
                        value={createTransId}
                        onChange={(e) => setCreateTransId(e.target.value)}
                        className="mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex justify-end gap-3 border-t border-gray-100 bg-gray-50/70 px-6 py-4 shrink-0 rounded-b-2xl">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50 shadow-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="rounded-xl bg-[var(--ink)] px-5 py-2 text-xs font-semibold text-white shadow-sm hover:opacity-90 disabled:opacity-50"
                >
                  {isSubmitting ? "Generating..." : "Generate E-Way Bill"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default function EwayBillPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center">
          <div className="flex items-center gap-3 text-sm text-[var(--ink-muted)]">
            <RefreshCw className="h-5 w-5 animate-spin text-[var(--accent)]" />
            <span>Loading E-Way Bill workbench...</span>
          </div>
        </div>
      }
    >
      <EwayBillWorkbenchContent />
    </Suspense>
  );
}
