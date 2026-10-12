import { NextRequest, NextResponse } from "next/server";
import { COGNITO_COOKIE_NAMES } from "@/lib/cognito/cookies";
import { verifyCognitoAccessToken } from "@/lib/cognito/jwt";
import { resolveBackendProxyAuth } from "@/lib/cognito/sessionBridge";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "https://api.recondesk.in").replace(
  /\/+$/,
  ""
);

/** Fail GETs that hang behind a stuck worker instead of skeleton forever. */
const PROXY_GET_TIMEOUT_MS = 90_000;

/**
 * Same-origin proxy to the FastAPI backend.
 * Browser calls hit Next.js first so cold-start / transport failures become
 * HTTP 502 instead of opaque "Failed to fetch" (which wrongly triggers the
 * Connection-lost banner).
 *
 * AWS Cognito Production Auth:
 * 1. Caller Authorization header (highest priority)
 * 2. Verified Cognito access-token cookie
 * 3. Fails closed / unauthenticated
 */
export async function proxyToBackend(
  request: NextRequest,
  targetPath: string
): Promise<NextResponse> {
  const url = new URL(targetPath, `${API_URL}/`);
  url.search = request.nextUrl.search;

  const headers = new Headers();
  const auth = request.headers.get("authorization");

  const resolvedAuth = await resolveBackendProxyAuth({
    incomingAuthHeader: auth,
    getCognitoToken: () => {
      return request.cookies.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value;
    },
    verifyCognitoToken: async (token: string) => {
      await verifyCognitoAccessToken({ token });
    },
  });

  if (resolvedAuth) {
    headers.set("Authorization", resolvedAuth);
  }

  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const accept = request.headers.get("accept");
  if (accept) headers.set("Accept", accept);

  const isGet = request.method === "GET" || request.method === "HEAD";
  const body = isGet ? undefined : await request.arrayBuffer();

  let backendRes: Response;
  try {
    backendRes = await fetch(url.toString(), {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      // Uploads / long POSTs stay uncapped; only GETs get a hard deadline.
      ...(isGet ? { signal: AbortSignal.timeout(PROXY_GET_TIMEOUT_MS) } : {}),
    });
  } catch (err) {
    const aborted =
      err instanceof Error &&
      (err.name === "TimeoutError" || err.name === "AbortError");
    console.error("[backend proxy] fetch failed:", url.toString(), err);
    return NextResponse.json(
      {
        detail: aborted
          ? "Backend timeout — the server took too long to respond"
          : "Backend unreachable",
      },
      { status: aborted ? 504 : 502 }
    );
  }

  const responseHeaders = new Headers();
  const backendContentType = backendRes.headers.get("content-type");
  if (backendContentType) {
    responseHeaders.set("Content-Type", backendContentType);
  }

  if (backendRes.status === 204) {
    return new NextResponse(null, { status: 204, headers: responseHeaders });
  }

  const responseBody = await backendRes.arrayBuffer();
  return new NextResponse(responseBody, {
    status: backendRes.status,
    headers: responseHeaders,
  });
}

export function backendProxyHandlers(pathPrefix: string) {
  type RouteContext = { params?: { path?: string[] } };

  async function handle(request: NextRequest, context?: RouteContext) {
    const segments = context?.params?.path ?? [];
    const targetPath =
      segments.length > 0
        ? `${pathPrefix}/${segments.map(encodeURIComponent).join("/")}`
        : pathPrefix;
    return proxyToBackend(request, targetPath);
  }

  return {
    GET: handle,
    POST: handle,
    PATCH: handle,
    PUT: handle,
    DELETE: handle,
    OPTIONS: handle,
  };
}
