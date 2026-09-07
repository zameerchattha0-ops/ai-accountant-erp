import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.supabase.co" },
    ],
    // Default imageSizes (16-384) plus the logo render widths used by the
    // app (120/180/480).  Without these the optimizer returns
    // 400 '"w" parameter (width) of N is not allowed' and every
    // next/image logo renders as a broken image (alt text only).
    imageSizes: [16, 32, 48, 64, 96, 120, 128, 180, 256, 384, 480],
  },
};

export default nextConfig;
