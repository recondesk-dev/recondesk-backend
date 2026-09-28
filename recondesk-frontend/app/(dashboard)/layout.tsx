export const dynamic = "force-dynamic";

import { AppSWRProvider } from "@/components/providers/AppSWRProvider";
import DashboardShellLayout from "@/components/dashboard/DashboardShellLayout";


export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AppSWRProvider>
      <div className="font-sans min-h-screen">
        <DashboardShellLayout>{children}</DashboardShellLayout>
      </div>
    </AppSWRProvider>
  );
}
