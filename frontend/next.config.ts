import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Proxy /api and /ws to FastAPI when running Next.js dev server directly (port 3000).
  // In production (accessed via nginx on port 80), nginx handles the proxying instead.
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
    return [
      { source: "/health", destination: `${backendUrl}/health` },
      { source: "/api/:path*", destination: `${backendUrl}/api/:path*` },
      { source: "/ws/:path*", destination: `${backendUrl}/ws/:path*` },
    ];
  },

  experimental: {
    middlewareClientMaxBodySize: "50mb",
  },
};

export default nextConfig;
