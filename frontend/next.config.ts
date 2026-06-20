import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow hot-module-replacement when accessed from network IP
  // (e.g. from another device on the same network or WSL)
  allowedDevOrigins: [
    "10.28.251.68",
    "10.84.83.68",
    "localhost",
    "127.0.0.1",
  ],
};

export default nextConfig;
