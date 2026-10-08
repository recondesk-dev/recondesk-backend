import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { COGNITO_COOKIE_NAMES } from "@/lib/cognito/cookies";
import { verifyCognitoAccessToken } from "@/lib/cognito/jwt";
import { resolveAccessTokenBridge } from "@/lib/cognito/sessionBridge";

/**
 * Returns the current user's access JWT using server-side cookie inspection.
 *
 * AWS Cognito Production Auth:
 *   1. Valid Cognito access-token cookie (provider="cognito")
 *   2. 401 Unauthorized
 *
 * Security:
 * - Refresh tokens are NEVER exposed to the browser.
 * - Cognito tokens are locally verified (RS256, issuer, client_id, exp, token_use=access).
 * - Fails closed to 401 if invalid/expired; never silently falls back.
 */
export async function GET(request: NextRequest) {
  const result = await resolveAccessTokenBridge({
    getCognitoCookie: () => {
      let token = request.cookies.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value;
      if (!token) {
        try {
          token = cookies().get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value;
        } catch {
          // Non-request context
        }
      }
      return token;
    },
    verifyCognitoToken: async (token: string) => {
      await verifyCognitoAccessToken({ token });
    },
  });

  return NextResponse.json(result.body, { status: result.status });
}
