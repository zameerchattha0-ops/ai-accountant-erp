import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    rules: {
      // The pages fetch from Supabase directly in useEffect via async loaders;
      // every setState happens after `await`, so renders don't cascade. The
      // rule's flow-insensitive analysis false-positives on this standard
      // fetch-on-mount pattern (no React Query/SWR in the stack yet).
      "react-hooks/set-state-in-effect": "off",
    },
  },
]);

export default eslintConfig;
