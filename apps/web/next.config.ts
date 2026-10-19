import type { NextConfig } from "next";
const api = new URL(process.env.ALAP_API_ORIGIN || "http://127.0.0.1:8000");
if (
  api.username ||
  api.password ||
  api.search ||
  api.hash ||
  api.pathname !== "/"
)
  throw new Error("Invalid API origin");
const config: NextConfig = {
  poweredByHeader: false,
  experimental: { useTypeScriptCli: false, cpus: 2 },
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${api.origin}/api/v1/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Cache-Control", value: "no-store" },
        ],
      },
    ];
  },
};
export default config;
