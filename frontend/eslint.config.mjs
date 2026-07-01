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
      // Flag genuinely magic numbers without blocking every PR on array
      // indices, HTTP status codes, or the usual 0/1/-1/2 arithmetic.
      "no-magic-numbers": [
        "warn",
        {
          ignore: [-1, 0, 1, 2, 100, 200, 400, 404, 500],
          ignoreArrayIndexes: true,
          ignoreDefaultValues: true,
          ignoreClassFieldInitialValues: true,
          detectObjects: false,
          enforceConst: false,
        },
      ],
    },
  },
]);

export default eslintConfig;
