import { NextRequest, NextResponse } from 'next/server';

const BACKEND_BASE = (
  process.env.BACKEND_URL ||
  (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(/\/api\/?$/, '')
);

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;

  // Reject any traversal attempt — segments must be plain filenames/IDs
  if (path.some((seg) => seg === '..' || seg === '.' || seg.includes('/'))) {
    return new NextResponse(null, { status: 400 });
  }

  const joined = path.join('/');
  if (!joined.startsWith('static/snapshots/')) {
    return new NextResponse(null, { status: 403 });
  }

  const upstreamUrl = `${BACKEND_BASE}/${joined}`;

  // Snapshot delivery is authenticated and ownership-checked upstream, so the
  // caller's credentials have to travel with the request. Without this the
  // proxy would be an anonymous read hole around that check.
  const authToken = request.cookies.get('auth_token')?.value;
  if (!authToken) {
    return new NextResponse(null, { status: 401 });
  }

  let res: Response;
  try {
    res = await fetch(upstreamUrl, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
  } catch {
    return new NextResponse(null, { status: 502 });
  }

  if (!res.ok) {
    return new NextResponse(null, { status: res.status });
  }

  const buffer = await res.arrayBuffer();
  const contentType = res.headers.get('content-type') || 'application/octet-stream';
  return new NextResponse(buffer, {
    headers: {
      'Content-Type': contentType,
      // private: this media belongs to one user, so no shared cache may keep it
      'Cache-Control': 'private, max-age=3600',
    },
  });
}
