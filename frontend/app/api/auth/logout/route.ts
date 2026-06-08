import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  const host = request.headers.get('x-forwarded-host') || request.headers.get('host') || 'localhost:3000';
  const proto = request.headers.get('x-forwarded-proto') || 'http';
  const response = NextResponse.redirect(`${proto}://${host}/login`);
  response.cookies.delete('auth_token');
  response.cookies.delete('refresh_token');
  return response;
}
