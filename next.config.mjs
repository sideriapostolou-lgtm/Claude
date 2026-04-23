/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    serverActions: { bodySizeLimit: "2mb" },
  },
  eslint: { ignoreDuringBuilds: false },
};

export default nextConfig;
