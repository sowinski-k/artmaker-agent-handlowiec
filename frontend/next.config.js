/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',  // dla Docker - bundle z node_modules w .next/standalone
  reactStrictMode: true,
  // FastAPI backend URL - przekazywany przez Railway internal networking
  env: {
    BACKEND_URL: process.env.BACKEND_URL || 'http://localhost:8000',
  },
  async rewrites() {
    return [
      // Proxy do FastAPI backendu - frontend wola /api/*, Next przekierowuje
      {
        source: '/api/:path*',
        destination: `${process.env.BACKEND_URL || 'http://localhost:8000'}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
