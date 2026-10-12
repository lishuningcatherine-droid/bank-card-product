import type { NextConfig } from "next";

const apiPublic = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const isDev = process.env.NODE_ENV !== "production";

// CSP without nonces (documented trade-off): Next.js needs inline bootstrap scripts; nonces would force every page
// to render dynamically. No third-party scripts are loaded and connect-src is limited to this site and the API.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  `connect-src 'self' ${apiPublic}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    const h = [
      { key: "Content-Security-Policy", value: csp },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), interest-cohort=()" },
    ];
    if (!isDev) h.push({ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" });
    return [{ source: "/:path*", headers: h }];
  },
};

export default config;
