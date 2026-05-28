import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  output: "standalone",
  turbopack: {
    root: path.resolve(__dirname),
  },
  allowedDevOrigins: ["172.30.1.38"],
};

export default nextConfig;
