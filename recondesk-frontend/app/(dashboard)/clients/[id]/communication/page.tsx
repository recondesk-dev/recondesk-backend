import { redirect } from "next/navigation";

import CommunicationCenter from "@/components/communication/CommunicationCenter";
import { getAuthenticatedCognitoUser } from "@/lib/cognito/serverAuth";
import { createAdminClient } from "@/lib/supabase/admin";

export default async function CommunicationPage({
  params,
}: {
  params: { id: string };
}) {
  const user = await getAuthenticatedCognitoUser();
  if (!user) {
    redirect("/login");
  }

  const adminDb = createAdminClient();
  const { data: clientRow } = (await adminDb
    .from("client_gstins")
    .select("firm_owner_id")
    .eq("id", params.id)
    .maybeSingle()) as { data: { firm_owner_id: string } | null; error: unknown };

  const organizationId = clientRow?.firm_owner_id ?? user.id;

  return (
    <CommunicationCenter
      clientId={params.id}
      organizationId={organizationId}
      userId={user.id}
    />
  );
}
