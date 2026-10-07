import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const APP = fs.readFileSync(new URL("./app.js", import.meta.url), "utf8");
const LINES = APP.split("\n");

// escapeHtml escapes & < > through the DOM, so it is right for text nodes and wrong inside a
// quoted attribute: it leaves " ' and ` alone, which is all an attacker needs to close the
// attribute and add another one. escapeAttr is escapeHtml plus those three. CSP blocks the
// obvious payload (no unsafe-inline), so the exposure here is DOM clobbering and a rewritten
// data-source -- quiet, but real, and invisible to every other test in this folder.
const TEXT_ONLY = /[\w-]+="[^"]*escapeHtml\(/g;

function textOnlyInAttributes() {
  const found = [];
  LINES.forEach((line, index) => {
    TEXT_ONLY.lastIndex = 0;
    if (TEXT_ONLY.test(line)) found.push(index + 1);
  });
  return found;
}

test("no text-only escaper is used inside an attribute", () => {
  const offenders = textOnlyInAttributes();
  assert.deepEqual(
    offenders,
    [],
    `escapeHtml() cannot stop an attribute break-out; use escapeAttr() at lines ${offenders.join(", ")}`,
  );
});

// These attributes are read back with getAttribute/dataset and decide which track, source or
// chat an action applies to. An unescaped one is a click that operates on something else.
const IDENTITY_ATTRIBUTES = [
  "data-bulk-source",
  "data-candidate",
  "data-chat",
  "data-contact",
  "data-global-source",
  "data-global-track",
  "data-play-key",
  "data-queue-key",
  "data-row-like-key",
  "data-source",
  "data-source-menu",
  "data-temporary-source",
  "data-track-key",
];

test("identity attributes always carry an attribute-safe value", () => {
  const offenders = [];
  LINES.forEach((line, index) => {
    for (const attribute of IDENTITY_ATTRIBUTES) {
      const pattern = new RegExp(`\\b${attribute}="([^"]*)"`, "g");
      let match;
      while ((match = pattern.exec(line))) {
        const value = match[1];
        // Selector strings legitimately use CSS.escape instead of escapeAttr.
        if (value.includes("${") && !/escapeAttr\(|CSS\.escape\(/.test(value)) {
          offenders.push(`${index + 1}: ${attribute}="${value}"`);
        }
      }
    }
  });
  assert.deepEqual(offenders, []);
});

test("escapeAttr holds an attribute shut where escapeHtml does not", () => {
  // app.js is not a module, so the two helpers are lifted out verbatim rather than copied into
  // the test -- a copied expectation would drift from the shipped code.
  const source = LINES.filter((line) => /^function escape(Html|Attr)\(/.test(line)).join("\n");
  assert.match(source, /function escapeHtml\(/);
  assert.match(source, /function escapeAttr\(/);
  const document = {
    createElement: () => {
      let text = "";
      return {
        set textContent(value) {
          text = value ?? "";
        },
        get innerHTML() {
          return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        },
      };
    },
  };
  const { escapeAttr } = new Function("document", `${source}; return { escapeHtml, escapeAttr };`)(
    document,
  );

  // A trailing backtick has to be spelled as an escape: written literally it closes this very
  // template literal and the payload silently loses the character being tested.
  const backtick = String.fromCharCode(96);
  const payload = `x" aria-label="pwned onerror=alert(1)${backtick}`;
  const escaped = escapeAttr(payload);
  assert.ok(escaped.includes("&#96;"), "an unescaped backtick would re-open the template literal");
  assert.ok(!escaped.includes('"'), "a raw quote must survive nowhere in an attribute value");
  assert.ok(!escaped.includes(backtick), "no raw backtick may survive either");
  // The attribute the row was built with stays the only attribute.
  assert.equal(`aria-label="${escaped}"`, 'aria-label="x&quot; aria-label=&quot;pwned onerror=alert(1)&#96;"');
  // Text nodes must not be double-escaped on the way through.
  assert.equal(escapeAttr("<b>Tom & Jerry</b>"), "&lt;b&gt;Tom &amp; Jerry&lt;/b&gt;");
});
