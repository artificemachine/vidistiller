import { NextRequest, NextResponse } from 'next/server';

const BACKEND_BASE = (
  process.env.BACKEND_URL ||
  (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(/\/api\/?$/, '')
);

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const upstreamUrl = `${BACKEND_BASE}/${path.join('/')}`;

  let res: Response;
  try {
    res = await fetch(upstreamUrl);
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
      'Cache-Control': 'public, max-age=3600',
    },
  });
}
