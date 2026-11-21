import type { NextConfig } from "next";

const api = process.env.SHERPA_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // standalone only for the Docker image (web/Dockerfile sets it); `next start` warns on a standalone build
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // pin the app root: otherwise Next.js goes looking for lockfiles in parent directories
  outputFileTracingRoot: __dirname,
  turbopack: { root: __dirname },
  agentRules: false, // `next dev` would otherwise write AGENTS.md into the repo
  compress: false, // gzip buffers the /api/ask SSE stream; stages must arrive as they happen
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
