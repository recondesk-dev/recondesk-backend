import type { Metadata } from "next";

import UploadPageClient from "@/components/upload/UploadPageClient";

export const metadata: Metadata = {
  title: "Upload Documents — ReconDesk",
};

export default function UploadPage({ params }: { params: { token: string } }) {
  return <UploadPageClient token={params.token} />;
}
