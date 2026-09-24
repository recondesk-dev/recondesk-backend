import type { Metadata } from "next";
import VendorResponsePortalClient from "@/components/vendor-portal/VendorResponsePortalClient";

export const metadata: Metadata = {
  title: "GST Reconciliation & ITC Verification Portal — ReconDesk",
  description: "Secure vendor response portal for GSTR-1 filing status, Rule 37 compliance, and invoice verification under CGST Act, 2017.",
};

export default function VendorPortalPage({ params }: { params: { token: string } }) {
  return <VendorResponsePortalClient token={params.token} />;
}
