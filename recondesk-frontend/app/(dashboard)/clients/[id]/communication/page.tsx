import { redirect } from "next/navigation";

import CommunicationCenter from "@/components/communication/CommunicationCenter";
import { createClient } from "@/lib/supabase/server";

export default async function CommunicationPage({
  params,
}: {
  params: { id: string };
}) {
  const supabase = createClient();
  if (!supabase) {
    redirect("/login");
  }

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const { data: clientRow } = await supabase
    .from("client_gstins")
    .select("firm_owner_id")
    .eq("id", params.id)
    .maybeSingle();

  const organizationId = clientRow?.firm_owner_id ?? user.id;

  return (
    <CommunicationCenter
      clientId={params.id}
      organizationId={organizationId}
      userId={user.id}
    />
  );
}
