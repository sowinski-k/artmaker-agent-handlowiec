/* Catch-all API proxy route.
 *
 * Wszystkie /api/* requesty z frontendu (przegladarka) trafiaja tutaj
 * (server-side Next.js), a my przekierowujemy je do backend FastAPI.
 *
 * Dlaczego tak:
 *  - frontend gada same-origin (zero CORS)
 *  - process.env.BACKEND_URL jest evaluated RUNTIME, nie build-time
 *    -> zmiana env w Railway dziala po RESTART (a nie REBUILD)
 *  - jezeli zmienisz URL backendu, restart frontu = OK
 *  - cookies przekazywane natywnie (same domena w przegladarce)
 */

import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function backendUrl(): string {
  const raw = process.env.BACKEND_URL || 'http://localhost:8000';
  return raw.replace(/\/$/, '');
}

async function proxy(
  req: NextRequest,
  pathSegments: string[],
): Promise<NextResponse> {
  const BACKEND = backendUrl();
  const path = pathSegments.join('/');
  const search = req.nextUrl.search || '';
  const url = `${BACKEND}/api/${path}${search}`;

  // Forward headers - usun Host (rozne dla frontu i backendu)
  const fwdHeaders = new Headers();
  for (const [k, v] of req.headers.entries()) {
    const key = k.toLowerCase();
    if (key === 'host' || key === 'content-length' || key === 'connection') continue;
    fwdHeaders.set(k, v);
  }

  const init: RequestInit = {
    method: req.method,
    headers: fwdHeaders,
    redirect: 'manual',
  };

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    try {
      init.body = await req.text();
    } catch {
      // brak body, OK
    }
  }

  try {
    const upstream = await fetch(url, init);
    const body = await upstream.arrayBuffer();

    // Skopiuj odpowiedz, ale przepisz Set-Cookie zeby browser zapisal cookie
    // pod domena frontu (same-origin) zamiast pod backend domena
    const respHeaders = new Headers();
    for (const [k, v] of upstream.headers.entries()) {
      const key = k.toLowerCase();
      if (key === 'content-encoding' || key === 'content-length' ||
          key === 'transfer-encoding' || key === 'connection') continue;
      respHeaders.append(k, v);
    }

    return new NextResponse(body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: respHeaders,
    });
  } catch (err) {
    return NextResponse.json(
      {
        detail: 'Backend unreachable',
        backend: BACKEND,
        error: err instanceof Error ? err.message : String(err),
      },
      { status: 502 },
    );
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
export async function POST(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
export async function PUT(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
export async function PATCH(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
export async function DELETE(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
