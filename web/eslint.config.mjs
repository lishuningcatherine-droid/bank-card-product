import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const config = [
  ...nextVitals,
  ...nextTs,
  { ignores: [".next/**", "node_modules/**", "src/lib/api/types.gen.ts", "playwright-report/**", "test-results/**",
              "next-env.d.ts"] },
  {
    rules: {
      "no-restricted-imports": ["error", { patterns: [{ group: ["**/legacy/**", "legacy/*"],
                                                         message: "Production code must not import legacy/." }] }],
    },
  },
];
export default config;
