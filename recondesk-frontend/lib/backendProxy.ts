import { NextRequest, NextResponse } from "next/server";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  ""
);

/** Fail GETs that hang behind a stuck Railway worker instead of skeleton forever. */
const PROXY_GET_TIMEOUT_MS = 90_000;

/**
 * Same-origin proxy to the FastAPI backend.
 * Browser calls hit Next.js first so cold-start / transport failures become
 * HTTP 502 instead of opaque "Failed to fetch" (which wrongly triggers the
 * Connection-lost banner).
 */
export async function proxyToBackend(
  request: NextRequest,
  targetPath: string
): Promise<NextResponse> {
  const url = new URL(targetPath, `${API_URL}/`);
  url.search = request.nextUrl.search;

  const headers = new Headers();
  const auth = request.headers.get("authorization");
  if (auth) headers.set("Authorization", auth);
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const accept = request.headers.get("accept");
  if (accept) headers.set("Accept", accept);

  let body: string | undefined;
  const isGet = request.method === "GET" || request.method === "HEAD";
  if (!isGet) {
    body = await request.text();
  }

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
  type RouteContext = { params: { path: string[] } };

  async function handle(request: NextRequest, context: RouteContext) {
    const segments = context.params.path ?? [];
    const targetPath = `${pathPrefix}/${segments.map(encodeURIComponent).join("/")}`;
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
