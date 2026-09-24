import type { Metadata } from "next";
import { LegalPage, LegalSection, LegalStrong } from "@/components/public/LegalPage";

export const metadata: Metadata = {
  title: "Security & Data Governance — ReconDesk",
  description:
    "Security practices, data encryption, and confidentiality architecture for ReconDesk (recondesk.in).",
};

export default function SecurityPage() {
  return (
    <LegalPage title="Security & Data Governance Guarantee" lastUpdated="September 2026">
      <LegalSection title="Confidentiality Commitment to CA Firms">
        <p>
          At <LegalStrong>ReconDesk</LegalStrong>, we recognize that Chartered Accountants, tax practitioners,
          and finance professionals entrust us with their clients&apos; most sensitive business data:
          purchase registers, sales invoices, vendor transaction histories, and GST returns.
        </p>
        <p>
          Our security architecture is designed from the ground up to ensure strict confidentiality, tenant
          isolation, and regulatory compliance with Indian data protection laws, including the
          <LegalStrong> Information Technology Act, 2000</LegalStrong> and the
          <LegalStrong> Digital Personal Data Protection (DPDP) Act, 2023</LegalStrong>.
        </p>
      </LegalSection>

      <LegalSection title="Data Encryption Standards">
        <p>
          All data processed by ReconDesk is protected by state-of-the-art cryptographic standards:
        </p>
        <ul className="list-disc pl-5 space-y-1.5">
          <li>
            <LegalStrong>Encryption in Transit:</LegalStrong> All traffic between your browser and our servers
            is enforced over TLS 1.3 with 256-bit encryption. Plain HTTP requests are automatically upgraded
            and redirected.
          </li>
          <li>
            <LegalStrong>Encryption at Rest:</LegalStrong> All database storage, document storage, and backups
            are encrypted using industry-standard AES-256 encryption.
          </li>
          <li>
            <LegalStrong>Sovereign Indian Data Residency:</LegalStrong> ReconDesk infrastructure is deployed
            exclusively in AWS Asia Pacific (Mumbai, ap-south-1) data centers, ensuring your clients&apos;
            financial records never leave Indian territorial borders.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="Tenant Isolation & Access Control">
        <p>
          Every Chartered Accountancy practice or business account on ReconDesk operates within an isolated
          tenant environment. Cross-firm data leakage is prevented at both the application logic level and
          database schema level:
        </p>
        <ul className="list-disc pl-5 space-y-1.5">
          <li>
            <LegalStrong>Row-Level & Schema Isolation:</LegalStrong> Every database query requires verified
            organization and client identification. No firm can ever access or query another firm&apos;s records.
          </li>
          <li>
            <LegalStrong>Role-Based Access Control (RBAC):</LegalStrong> Firms can manage staff access with
            granular permissions (Admin, Associate, Reviewer), ensuring team members only access assigned clients.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="GSTN Credentials & Session Security">
        <p>
          When you connect to the GST Portal via GSP/GSTN APIs:
        </p>
        <ul className="list-disc pl-5 space-y-1.5">
          <li>
            <LegalStrong>Zero Password Storage:</LegalStrong> ReconDesk never asks for or stores your GST portal
            login passwords.
          </li>
          <li>
            <LegalStrong>Ephemeral OTP Tokens:</LegalStrong> Authentication is conducted via standard GSTN OTP.
            Session tokens expire automatically after the statutory 6-hour window and are never logged or exposed.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="Data Ownership & 1-Click Purge">
        <p>
          You retain 100% ownership of all uploaded files, registers, and generated workpapers. ReconDesk will
          never sell, monetize, or use your client data to train machine learning models.
        </p>
        <p>
          Firms can permanently purge raw upload files or delete entire reconciliation runs at any time. When
          purged, data is deleted irreversibly across all active storage partitions.
        </p>
      </LegalSection>

      <LegalSection title="Reporting Security Vulnerabilities">
        <p>
          If you discover a potential security vulnerability or have questions regarding data privacy and
          protection, please reach out directly to our security team at{" "}
          <a
            href="mailto:support@recondesk.in"
            className="font-medium text-[#7B5CFA] hover:underline"
          >
            support@recondesk.in
          </a>
          .
        </p>
      </LegalSection>
    </LegalPage>
  );
}
