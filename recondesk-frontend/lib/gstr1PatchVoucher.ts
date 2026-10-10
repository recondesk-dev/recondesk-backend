/**
 * GSTR-1 In-App Quick-Patch & Tally Sync-Back Voucher generator.
 *
 * Enables CAs and tax accountants to:
 * 1. Generate an Audit Diff CSV spreadsheet showing all in-browser edits.
 * 2. Generate a valid Tally Prime XML import file so the client's books
 *    can be updated to stay 100% synchronized with the filed GST return.
 */

import { downloadBlobAsFile } from "@/lib/download";

export type Gstr1PatchRecord = {
  row_number?: number | string;
  invoice_number: string;
  invoice_date?: string;
  taxable_amount_paise?: number;
  field_name: "gstin" | "place_of_supply" | "invoice_type" | "note_type" | "export_type";
  original_value: string;
  patched_value: string;
  reason?: string;
  timestamp: string;
  party_name?: string;
  // Payload fields to send to backend orchestrator
  patch_data: {
    row_number?: number;
    invoice_number: string;
    gstin?: string;
    place_of_supply?: string;
    invoice_type?: string;
    note_type?: string;
    export_type?: string;
  };
};

function csvEscape(value: unknown): string {
  const s = value == null ? "" : String(value);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

export function downloadAuditDiffCsv(
  patches: Gstr1PatchRecord[],
  filingPeriod: string,
  gstin: string
): void {
  const headers = [
    "Filing Period",
    "Filer GSTIN",
    "Row Number",
    "Invoice Number",
    "Invoice Date",
    "Customer / Party",
    "Field Modified",
    "Original Value (ERP Books)",
    "Patched Value (Filed on Portal)",
    "Correction Reason / Note",
    "Timestamp (IST)",
  ];

  const rows = patches.map((p) => [
    filingPeriod,
    gstin,
    p.row_number || "—",
    p.invoice_number,
    p.invoice_date || "—",
    p.party_name || "—",
    p.field_name.toUpperCase(),
    p.original_value || "(Blank)",
    p.patched_value,
    p.reason || "Corrected for GSTN filing compliance",
    p.timestamp,
  ]);

  const csvContent = [
    headers.map(csvEscape).join(","),
    ...rows.map((r) => r.map(csvEscape).join(",")),
  ].join("\n");

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8" });
  const filename = `ReconDesk_ERP_Rectification_Diff_${gstin}_${filingPeriod}.csv`;
  downloadBlobAsFile(blob, filename);
}

export function downloadTallyRectificationXml(
  patches: Gstr1PatchRecord[],
  filingPeriod: string,
  companyName: string,
  gstin: string
): void {
  const safeComp = (companyName || "Client Company")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  const messageItems = patches
    .map((p) => {
      const invNo = (p.invoice_number || "").replace(/&/g, "&amp;");
      const cleanGstin = (p.patch_data.gstin || p.patched_value || "").replace(/&/g, "&amp;");
      const cleanPos = (p.patch_data.place_of_supply || "").replace(/&/g, "&amp;");
      const cleanReason = (p.reason || "GSTR-1 return filing rectification").replace(/&/g, "&amp;");

      return `      <TALLYMESSAGE xmlns:UDF="TallyUDF">
       <VOUCHER VCHTYPE="Sales" ACTION="Alter">
        <VOUCHERNUMBER>${invNo}</VOUCHERNUMBER>
        <NARRATION>ReconDesk GST Rectification: ${cleanReason} (Period: ${filingPeriod})</NARRATION>
        <PARTYGSTIN>${cleanGstin}</PARTYGSTIN>
        ${cleanPos ? `<PLACEOFSUPPLY>${cleanPos}</PLACEOFSUPPLY>` : ""}
        <BASICBUYERADDRESS.LIST>
         <BASICBUYERADDRESS>${cleanGstin}</BASICBUYERADDRESS>
        </BASICBUYERADDRESS.LIST>
       </VOUCHER>
      </TALLYMESSAGE>`;
    })
    .join("\n");

  const xmlContent = `<?xml version="1.0" encoding="utf-8"?>
<ENVELOPE>
 <HEADER>
  <TALLYREQUEST>Import Data</TALLYREQUEST>
 </HEADER>
 <BODY>
  <IMPORTDATA>
   <REQUESTDESC>
    <REPORTNAME>Vouchers</REPORTNAME>
    <STATICVARIABLES>
     <SVCURRENTCOMPANY>${safeComp}</SVCURRENTCOMPANY>
    </STATICVARIABLES>
   </REQUESTDESC>
   <REQUESTDATA>
${messageItems}
   </REQUESTDATA>
  </IMPORTDATA>
 </BODY>
</ENVELOPE>`;

  const blob = new Blob([xmlContent], { type: "application/xml;charset=utf-8" });
  const filename = `ReconDesk_Tally_Rectification_${gstin}_${filingPeriod}.xml`;
  downloadBlobAsFile(blob, filename);
}
