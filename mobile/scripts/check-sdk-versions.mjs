/**
 * Fail if any Expo-managed package drifts from the versions the installed SDK
 * was built against.
 *
 * This exists because a mismatch here does not fail the build — it produces an
 * APK that compiles, installs, and then crashes on launch:
 *
 *   NoClassDefFoundError: expo/modules/kotlin/types/AnyTypeProvider
 *     at expo.modules.securestore.SecureStoreModule.definition
 *
 * That was expo-secure-store 15.x sitting next to expo-modules-core 57.x. The
 * native module was compiled against an API that no longer existed. Nothing in
 * typecheck, bundling or Gradle notices; only launching the app does.
 *
 * `expo install --check` is the canonical tool, but it calls the Expo API and
 * so cannot run offline or behind a restrictive proxy. The same answer is in
 * `expo/bundledNativeModules.json`, shipped inside the installed SDK, which
 * makes this check work anywhere.
 *
 *   node scripts/check-sdk-versions.mjs
 */

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

function load(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

let bundled;
try {
  bundled = load(require.resolve('expo/bundledNativeModules.json'));
} catch {
  console.error('Could not find expo/bundledNativeModules.json — run npm install first.');
  process.exit(1);
}

const pkg = load('package.json');
const declared = { ...pkg.dependencies, ...pkg.devDependencies };

const problems = [];
for (const [name, expected] of Object.entries(bundled)) {
  if (!(name in declared)) continue;

  if (declared[name] !== expected) {
    problems.push({ name, kind: 'declared', found: declared[name], expected });
    continue;
  }

  // The declared range can be right while node_modules holds something else,
  // so check what is actually on disk too.
  try {
    const installed = load(require.resolve(`${name}/package.json`)).version;
    const wanted = expected.replace(/^[~^]/, '');
    const sameMajor = installed.split('.')[0] === wanted.split('.')[0];
    if (!sameMajor) {
      problems.push({ name, kind: 'installed', found: installed, expected });
    }
  } catch {
    problems.push({ name, kind: 'missing', found: '(not installed)', expected });
  }
}

if (problems.length === 0) {
  const count = Object.keys(bundled).filter((n) => n in declared).length;
  console.log(`SDK versions OK — ${count} Expo-managed packages match the installed SDK.`);
  process.exit(0);
}

console.error('Expo SDK version mismatch. These produce an APK that crashes on launch:\n');
for (const p of problems) {
  console.error(`  ${p.name.padEnd(28)} ${String(p.found).padEnd(14)} expected ${p.expected}  (${p.kind})`);
}
console.error('\nFix with:  npx expo install <package>   (never edit the version by hand)');
process.exit(1);
