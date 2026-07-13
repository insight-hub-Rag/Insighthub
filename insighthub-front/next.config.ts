import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Génère un bundle autonome dans .next/standalone
  // Indispensable pour le build Docker multi-stage (node server.js)
  output: "standalone",
};

export default nextConfig;
