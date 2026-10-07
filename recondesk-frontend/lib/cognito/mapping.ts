/**
 * Cognito-to-Aurora Trusted Account Mapping Lookup Client.
 *
 * Verifies whether an authenticated Cognito identity has a trusted, verified
 * 1:1 account mapping in AWS Aurora PostgreSQL via the backend API.
 *
 * Security Requirements:
 *   1. Never exposes Aurora database credentials or raw SQL to the frontend.
 *   2. Authenticated exclusively via Bearer Cognito Access Token (Requirement 5).
 *   3. Sends zero identity parameters (sub, user_id, email, pool_id) in the body or query (Requirement 4 & 5).
 *   4. Fails closed to 'pending_trusted_mapping_phase' on any network, parsing,
 *      or validation error.
 *   5. Response contains only account_mapping_status and user_id (when valid).
 */

export interface LookupCognitoMappingParams {
  accessToken: string;
  apiUrl?: string;
  fetchFn?: typeof fetch;
}

export interface CognitoMappingLookupResponse {
  account_mapping_status: "verified_mapping_found" | "pending_trusted_mapping_phase";
  user_id?: string | null;
}

/**
 * Queries the backend Aurora identity mapping service using the verified Cognito Access Token.
 *
 * Fails closed: returns { account_mapping_status: "pending_trusted_mapping_phase", user_id: null }
 * if the mapping is absent, unverified, inactive, or on any error.
 */
export async function lookupCognitoMapping(
  params: LookupCognitoMappingParams
): Promise<CognitoMappingLookupResponse> {
  const { accessToken, apiUrl, fetchFn = fetch } = params;

  const token = typeof accessToken === "string" ? accessToken.trim() : "";
  if (!token) {
    return {
      account_mapping_status: "pending_trusted_mapping_phase",
      user_id: null,
    };
  }

  const baseApiUrl = (
    apiUrl ||
    (process.env.INTERNAL_API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "https://api.recondesk.in")
  ).replace(/\/+$/, "");

  try {
    const res = await fetchFn(`${baseApiUrl}/api/v1/auth/cognito/lookup-mapping`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
    });

    if (!res.ok) {
      return {
        account_mapping_status: "pending_trusted_mapping_phase",
        user_id: null,
      };
    }

    const data = (await res.json()) as Partial<CognitoMappingLookupResponse>;
    if (
      data?.account_mapping_status === "verified_mapping_found" &&
      typeof data.user_id === "string" &&
      data.user_id.trim().length > 0
    ) {
      return {
        account_mapping_status: "verified_mapping_found",
        user_id: data.user_id.trim(),
      };
    }

    return {
      account_mapping_status: "pending_trusted_mapping_phase",
      user_id: null,
    };
  } catch (err: unknown) {
    // Fail closed on network failure, timeout, or invalid JSON
    return {
      account_mapping_status: "pending_trusted_mapping_phase",
      user_id: null,
    };
  }
}
