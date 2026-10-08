import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import CommunicationCenter from "@/components/communication/CommunicationCenter";
import { COGNITO_COOKIE_NAMES } from "@/lib/cognito/cookies";
import { verifyCognitoAccessToken } from "@/lib/cognito/jwt";

export default async function CommunicationPage({
  params,
}: {
  params: { id: string };
}) {
  const token = cookies().get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value;
  if (!token) {
    redirect("/login");
  }

  let claims;
  try {
    claims = await verifyCognitoAccessToken({ token });
  } catch {
    redirect("/login");
  }

  const userId = claims.sub || "user";

  return (
    <CommunicationCenter
      clientId={params.id}
      organizationId={userId}
      userId={userId}
    />
  );
}
