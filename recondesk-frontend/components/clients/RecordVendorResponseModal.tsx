"use client";

import React, { useState } from "react";
import {
  X,
  FileCheck2,
  AlertCircle,
  Calendar,
  UserCheck,
  Loader2,
  ShieldAlert,
  Info,
  Paperclip,
} from "lucide-react";
import { recordVendorResponse } from "@/lib/vendorFollowupApi";
import { useToast } from "@/components/providers/ToastProvider";

interface RecordVendorResponseModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRecorded: () => void;
  workItemId: string;
  vendorGstin: string;
  vendorName: string;
  isBlocking: boolean;
  currentStatus: string;
  token: string;
}

const CATEGORIES = [
  {
    id: "WILL_FILE_NEXT_PERIOD",
    label: "Will File in Next Period",
    description: "Vendor confirmed invoice will be included in their upcoming GSTR-1 filing.",
    stateImpact: "Status transitions to WAITING_VENDOR with target follow-up date.",
  },
  {
    id: "INVOICE_AMENDED",
    label: "Invoice Amended / Credit Note Issued",
    description: "Vendor issued an amendment or credit note. Requires revalidation.",
    stateImpact: "Status transitions to WAITING_VENDOR / IN_PROGRESS for next reconciliation cycle.",
  },
  {
    id: "DOCUMENT_PROVIDED",
    label: "Document / Clearance Proof Provided",
    description: "Vendor furnished tax invoice copy, e-way bill, or payment acknowledgment.",
    stateImpact: "Status transitions to IN_PROGRESS or READY_FOR_REVIEW for CA verification.",
  },
  {
    id: "DISPUTED",
    label: "Disputed by Vendor",
    description: "Vendor disputes amount, GST rate, or transaction validity.",
    stateImpact: "Status remains IN_PROGRESS; flagged for client and CA audit.",
  },
  {
    id: "NO_SUCH_INVOICE",
    label: "Vendor Has No Record of Invoice",
    description: "Vendor asserts invoice was never issued or cancelled. Potential internal error.",
    stateImpact: "Status remains IN_PROGRESS; flagged for purchase ledger audit.",
  },
  {
    id: "OTHER",
    label: "Other Operational Resolution",
    description: "General notes or alternative operational discussion with vendor.",
    stateImpact: "Status remains IN_PROGRESS unless explicitly updated.",
  },
];

export default function RecordVendorResponseModal({
  isOpen,
  onClose,
  onRecorded,
  workItemId,
  vendorGstin,
  vendorName,
  isBlocking,
  currentStatus,
  token,
}: RecordVendorResponseModalProps) {
  const toast = useToast();

  const [category, setCategory] = useState("WILL_FILE_NEXT_PERIOD");
  const [channel, setChannel] = useState("PHONE");
  const [contactPerson, setContactPerson] = useState("");
  const [promisedDate, setPromisedDate] = useState("");
  const [notes, setNotes] = useState("");
  const [evidenceFilename, setEvidenceFilename] = useState("");
  const [saving, setSaving] = useState(false);

  const selectedCategoryMeta = CATEGORIES.find((c) => c.id === category) || CATEGORIES[0];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !workItemId) return;

    if (!notes.trim()) {
      toast("Please enter detailed discussion notes or resolution summary", "error");
      return;
    }

    setSaving(true);
    try {
      await recordVendorResponse(
        workItemId,
        {
          response_category: category,
          contact_channel: channel,
          contact_person: contactPerson.trim() || undefined,
          promised_date: promisedDate || undefined,
          notes: notes.trim(),
          evidence_filename: evidenceFilename.trim() || undefined,
        },
        token
      );

      toast("Vendor response recorded to work item timeline.", "success");
      onRecorded();
      onClose();
    } catch (err: any) {
      toast(err?.detail || "Failed to record vendor response", "error");
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white rounded-xl shadow-2xl border border-gray-200 w-full max-w-xl max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-gray-50/50">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <FileCheck2 className="w-5 h-5 text-emerald-600" />
              Record Vendor Response
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {vendorName || vendorGstin} ({vendorGstin})
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 overflow-y-auto space-y-4 flex-1">
          {/* Statutory Rule Banner */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs text-blue-900 flex items-start gap-2">
            <Info className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold">Operational Invariant:</span> Vendor representations are
              evidence/information, not tax adjudication. Final ITC statutory eligibility is only established
              through authoritative reconciliation.
            </div>
          </div>

          {/* Response Category */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-700 mb-1.5">
              Response Category <span className="text-rose-500">*</span>
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full text-sm rounded-lg border border-gray-300 px-3 py-2 bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 font-medium"
            >
              {CATEGORIES.map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {cat.label}
                </option>
              ))}
            </select>

            {/* Category Explanation Banner */}
            <div className="mt-2 p-2.5 bg-gray-50 border border-gray-200 rounded-lg text-xs space-y-1">
              <p className="text-gray-700 font-medium">{selectedCategoryMeta.description}</p>
              <p className="text-indigo-700 font-semibold flex items-center gap-1.5">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-indigo-600" />
                {selectedCategoryMeta.stateImpact}
              </p>
            </div>
          </div>

          {/* Contact Details Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Communication Mode
              </label>
              <select
                value={channel}
                onChange={(e) => setChannel(e.target.value)}
                className="w-full text-sm rounded-lg border border-gray-300 px-3 py-2 bg-white text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="PHONE">Phone Call</option>
                <option value="EMAIL">Email Exchange</option>
                <option value="WHATSAPP">WhatsApp Chat</option>
                <option value="IN_PERSON">In-Person Meeting</option>
                <option value="LETTER">Written Notice / Letter</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Vendor Contact Person
              </label>
              <input
                type="text"
                value={contactPerson}
                onChange={(e) => setContactPerson(e.target.value)}
                placeholder="e.g. Mr. Sharma (Accounts Manager)"
                className="w-full text-sm rounded-lg border border-gray-300 px-3 py-2 text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>

          {/* Promised Follow-up Date */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1 flex items-center gap-1.5">
              <Calendar className="w-3.5 h-3.5 text-gray-500" />
              Promised Action / Filing Date (Sets Next Follow-up SLA)
            </label>
            <input
              type="date"
              value={promisedDate}
              onChange={(e) => setPromisedDate(e.target.value)}
              className="w-full text-sm rounded-lg border border-gray-300 px-3 py-2 text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <span className="text-[11px] text-gray-500 mt-1 block">
              Work item SLA will automatically track against this target date.
            </span>
          </div>

          {/* Discussion Notes */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-700 mb-1">
              Discussion Summary / Audit Notes <span className="text-rose-500">*</span>
            </label>
            <textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Record details of conversation, reasons provided by vendor, or specific commitments..."
              className="w-full text-sm rounded-lg border border-gray-300 p-3 text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500 placeholder-gray-400"
              required
            />
          </div>

          {/* Evidence Reference */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1 flex items-center gap-1.5">
              <Paperclip className="w-3.5 h-3.5 text-gray-500" />
              Evidence Document Reference (Optional)
            </label>
            <input
              type="text"
              value={evidenceFilename}
              onChange={(e) => setEvidenceFilename(e.target.value)}
              placeholder="e.g. Invoice_Copy_1024.pdf or bank_clearance_ref.pdf"
              className="w-full text-sm rounded-lg border border-gray-300 px-3 py-2 text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {/* Maker-Checker Warning if Blocking */}
          {isBlocking && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-900 flex items-start gap-2">
              <ShieldAlert className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold">Maker-Checker Protected:</span> This is a finalization-blocking
                exception. Recording a vendor response will transition the item for review, but cannot be
                resolved without CA sign-off.
              </div>
            </div>
          )}

          {/* Footer Buttons */}
          <div className="flex items-center justify-end gap-3 pt-3 border-t border-gray-200">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              Cancel
            </button>

            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-2 px-5 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50 transition-colors shadow-sm"
            >
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Recording Response...
                </>
              ) : (
                <>
                  <FileCheck2 className="w-4 h-4" />
                  Save Vendor Response
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
