import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 静的エクスポート(Cloudflare Pages / GitHub Pages等の静的ホスティング向け)
  output: "export",
};

export default nextConfig;
