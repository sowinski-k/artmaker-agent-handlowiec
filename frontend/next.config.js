/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output for Docker - bundles node_modules + server.js w .next/standalone
  output: 'standalone',
  reactStrictMode: true,
};

module.exports = nextConfig;
