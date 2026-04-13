export const dynamic = "force-dynamic";

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import DashboardShell from "@/components/layout/DashboardShell";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const meta = user.user_metadata ?? {};
  const userProfile = {
    full_name: meta.full_name ?? user.email?.split("@")[0] ?? "User",
    firm_name: meta.firm_name ?? "",
    role: (meta.role ?? "Staff") as "Admin" | "Staff",
    email: user.email ?? "",
  };

  return (
    <DashboardShell userProfile={userProfile}>
      {children}
    </DashboardShell>
  );
}
