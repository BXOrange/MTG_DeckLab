import globals from "globals";

export default [
  {
    files: ["src/js/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
    },
    rules: {
      "no-constant-binary-expression": "error",
      "no-dupe-else-if": "error",
      "no-dupe-keys": "error",
      "no-duplicate-case": "error",
      "no-duplicate-imports": "error",
      "no-fallthrough": "error",
      "no-console": "warn",
      "no-self-assign": "error",
      "no-undef": "error",
      "no-unreachable": "error",
    },
  },
];
