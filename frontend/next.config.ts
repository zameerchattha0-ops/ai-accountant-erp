import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.supabase.co" },
    ],
    // The Next.js image optimizer endpoint (/_next/image) is NOT available
    // when the frontend runs as a Vercel Service (it 404s for every width),
    // which rendered EVERY next/image logo as a broken image (sidebar,
    // login, signup, welcome, TopBar org logo). Render plain <img> instead
    // - the source files are served correctly as static assets.
    unoptimized: true,
  },
};

export default nextConfig;
