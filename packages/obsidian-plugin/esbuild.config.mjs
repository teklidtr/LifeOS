import { copyFile, mkdir, rm } from "node:fs/promises";

import { build } from "esbuild";

await rm("build", { recursive: true, force: true });
await mkdir("build", { recursive: true });

await build({
  entryPoints: ["src/obsidian-entry.ts"],
  outfile: "build/main.js",
  bundle: true,
  external: ["obsidian"],
  format: "cjs",
  platform: "node",
  target: "es2022",
  sourcemap: true,
  sourcesContent: false,
  treeShaking: true,
  logLevel: "info",
});

await Promise.all([
  copyFile("manifest.json", "build/manifest.json"),
  copyFile("styles.css", "build/styles.css"),
]);
