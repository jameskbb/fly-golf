// Resolve Playwright the way Node's require() does, so it is found in a local node_modules, in a
// global install exposed through NODE_PATH (e.g. `npm i -g playwright` and
// `NODE_PATH=$(npm root -g)`), or at an explicit PLAYWRIGHT_MODULE path. A bare ESM
// `import ... from "playwright"` would ignore NODE_PATH.
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

export function loadPlaywright() {
  const id = process.env.PLAYWRIGHT_MODULE || "playwright";
  try {
    return require(id);
  } catch (err) {
    throw new Error(
      `playwright not found (${id}). Install it where this script runs (npm i playwright), or ` +
        "install it globally and set NODE_PATH=$(npm root -g), or set PLAYWRIGHT_MODULE to its path.\n" +
        err.message,
    );
  }
}
