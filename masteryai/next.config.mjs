/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    serverActions: {
      allowedOrigins: ['localhost:3000'],
    },
  },
  // Allow reactflow and other packages to be transpiled
  transpilePackages: ['reactflow'],
}

export default nextConfig
