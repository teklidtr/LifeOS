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
  assert.match(source, /lifeos-open-proposals/);
  assert.match(source, /LifeOS Proposals/);
  assert.match(source, /Typed operations/);

  class Plugin {}
  class PluginSettingTab {}
  class ItemView {}
  class MarkdownView {}
  class Modal {}
  class App {}
  class FileSystemAdapter {}
  class TFile {}
  class Setting {}
  const obsidian = {
    Plugin,
    PluginSettingTab,
    ItemView,
    MarkdownView,
    MarkdownRenderer: { render: async () => {} },
    Modal,
    App,
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

test("proposal workspace artifact wraps long review text within its columns", async () => {
  const styles = await readFile(new URL("../build/styles.css", import.meta.url), "utf8");

  assert.match(styles, /\.lifeos-proposals\s*{[^}]*container:\s*lifeos-proposals \/ inline-size/s);
  assert.match(styles, /\.lifeos-proposals__workspace\s*{[^}]*min-width:\s*0/s);
  assert.match(styles, /button\.lifeos-proposals__proposal\s*{[^}]*overflow-wrap:\s*anywhere/s);
  assert.match(styles, /button\.lifeos-proposals__proposal\s*{[^}]*height:\s*auto/s);
  assert.match(styles, /button\.lifeos-proposals__proposal\s*{[^}]*min-height:\s*var\(--input-height\)/s);
  assert.match(styles, /\.lifeos-proposals__detail h3,[^{]*{[^}]*word-break:\s*break-word/s);
  assert.match(styles, /@container lifeos-proposals \(max-width:\s*48rem\)/);
});
