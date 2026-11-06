import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import prettierRecommended from "eslint-plugin-prettier/recommended";

const eslintConfig = [
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
      ".pnpm-store/**",
      "public/**",
    ],
  },
  ...nextCoreWebVitals,
  prettierRecommended,
  {
    // Phase 20 legacy audit: these specs run against the FINAL production
    // hostnames, resolved to loopback by Chromium's --host-resolver-rules.
    // Node-side HTTP (page.request, the `request` fixture, route.fetch, a
    // hand-rolled browser launch) honours neither that flag nor
    // --no-proxy-server and would reach the real production servers.
    files: ["e2e-legacy-audit/**/*.ts", "e2e-legacy/**/*.ts"],
    rules: {
      // Playwright fixtures take a `use` callback; it is not a React hook.
      "react-hooks/rules-of-hooks": "off",
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "MemberExpression[object.name='page'][property.name='request']",
          message:
            "page.request hits production: use apiFetch() from helpers/audit-env.ts.",
        },
        {
          selector:
            "MemberExpression[object.name='context'][property.name='request']",
          message:
            "context.request hits production: use apiFetch() from helpers/audit-env.ts.",
        },
        {
          selector: "ObjectPattern > Property[key.name='request']",
          message:
            "The `request` fixture hits production: use apiFetch() from helpers/audit-env.ts.",
        },
        {
          selector:
            "CallExpression[callee.property.name='fetch'][callee.object.name='route']",
          message:
            "route.fetch() runs in Node and hits production: use route.continue().",
        },
        {
          selector: "CallExpression[callee.property.name='launch']",
          message:
            "Launch browsers through the Playwright config so the resolver and proxy flags apply.",
        },
      ],
    },
  },
  {
    rules: {
      "@next/next/link-passhref": "off",
      "react/no-unescaped-entities": "off",
      // New rules from eslint-plugin-react-hooks@7 (shipped with
      // eslint-config-next@16). These surface pre-existing issues — downgrade
      // to warnings so the upgrade doesn't block on them; address as a
      // follow-up refactor.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/static-components": "warn",
    },
  },
];

export default eslintConfig;
