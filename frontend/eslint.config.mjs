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
  {
    // eslint-plugin-react-hooks "purity" lint (new React Compiler rule) falsely flags
    // module-level decorative initialization in GeometricShapes.tsx. The shapes are
    // randomly generated once at import and used immutably; the randomness is purely
    // for visual variation of static background graphics, not render-time mutation,
    // so the rule does not apply to this component.
    files: ["src/components/background/GeometricShapes.tsx"],
    rules: {
      "react-hooks/purity": "off",
    },
  },
]);

export default eslintConfig;
