export const dynamic = "force-dynamic";

import { AppSWRProvider } from "@/components/providers/AppSWRProvider";
import DashboardShellLayout from "@/components/dashboard/DashboardShellLayout";
import { BackgroundRunNotifier } from "@/components/providers/BackgroundRunNotifier";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AppSWRProvider>
      <div className="font-sans min-h-screen">
        <BackgroundRunNotifier />
        <DashboardShellLayout>{children}</DashboardShellLayout>
      </div>
    </AppSWRProvider>
  );
}
