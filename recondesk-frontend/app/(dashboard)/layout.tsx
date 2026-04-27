import { AppSWRProvider } from "@/components/providers/AppSWRProvider";
import DashboardShellLayout from "@/components/dashboard/DashboardShellLayout";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AppSWRProvider>
      <DashboardShellLayout>{children}</DashboardShellLayout>
    </AppSWRProvider>
  );
}
