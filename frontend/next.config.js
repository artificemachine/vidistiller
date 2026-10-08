const { withSentryConfig } = require("@sentry/nextjs");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    domains: ['i.ytimg.com', 'localhost'],
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || '/api',
  },
  experimental: {
    // The /api rewrite proxy clones request bodies and cuts them at 10 MB by
    // default, which truncates file uploads. Match the backend's default
    // MAX_VIDEO_UPLOAD_SIZE_BYTES (4 GiB); the backend still enforces its own cap.
    middlewareClientMaxBodySize: 4 * 1024 * 1024 * 1024,
  },
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: '/static/:path*',
        destination: `${backendUrl}/static/:path*`,
      },
    ];
  },
};

// Only wrap with Sentry when a DSN is configured
module.exports = process.env.NEXT_PUBLIC_SENTRY_DSN
  ? withSentryConfig(nextConfig, {
      silent: true,
      hideSourceMaps: true,
    })
  : nextConfig;
