import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { Script, createContext } from "node:vm";
import test from "node:test";

const nodeRequire = createRequire(import.meta.url);

test("production artifact is a self-contained Obsidian CommonJS plugin", async () => {
  const source = await readFile(new URL("../build/main.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /require\(["']\.\//);
  assert.doesNotMatch(source, /^\s*import\s/m);

  class Plugin {}
  class PluginSettingTab {}
  class ItemView {}
  class MarkdownView {}
  class FileSystemAdapter {}
  class TFile {}
  class Setting {}
  const obsidian = {
    Plugin,
    PluginSettingTab,
    ItemView,
    MarkdownView,
    FileSystemAdapter,
    TFile,
    Setting,
    getAllTags: () => [],
  };
  const module = { exports: {} };
  const context = createContext({
    module,
    exports: module.exports,
    process,
    Buffer,
    console,
    setTimeout,
    clearTimeout,
    require: (specifier) => specifier === "obsidian" ? obsidian : nodeRequire(specifier),
  });
  new Script(source, { filename: "build/main.js" }).runInContext(context);

  assert.equal(typeof module.exports.default, "function");
  assert.ok(module.exports.default.prototype instanceof Plugin);
});
