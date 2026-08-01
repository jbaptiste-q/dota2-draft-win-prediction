import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";

const siteRoot = new URL("../", import.meta.url);
const repositoryRoot = new URL("../../", import.meta.url);
const workerUrl = new URL("../dist/server/index.js", import.meta.url);
workerUrl.searchParams.set("parity", `${process.pid}-${Date.now()}`);
const { default: worker } = await import(workerUrl.href);

const context = {
  waitUntil() {},
  passThroughOnException() {},
};

async function fetchWorker(path, init = {}, env = {}) {
  return worker.fetch(
    new Request(`http://draft-lab.test${path}`, init),
    env,
    context,
  );
}

function pythonExecutable() {
  if (process.env.PYTHON_BIN) {
    return process.env.PYTHON_BIN;
  }
  const virtualEnvironmentPython = new URL(
    "../../.venv/bin/python",
    import.meta.url,
  );
  return existsSync(virtualEnvironmentPython)
    ? fileURLToPath(virtualEnvironmentPython)
    : "python3";
}

function loadPythonGolden() {
  const result = spawnSync(
    pythonExecutable(),
    [fileURLToPath(new URL("python_golden.py", import.meta.url))],
    {
      cwd: fileURLToPath(repositoryRoot),
      encoding: "utf8",
      env: {
        ...process.env,
        PYTHONDONTWRITEBYTECODE: "1",
      },
    },
  );
  assert.equal(
    result.status,
    0,
    `Python golden generation failed:\n${result.error ?? ""}\n${result.stderr ?? ""}`,
  );
  return JSON.parse(result.stdout);
}

const golden = loadPythonGolden();
const radiant = ["axe", "bane", "chen", "doom", "invoker"];
const dire = ["lina", "lion", "puck", "tiny", "zeus"];
const negativeRadiant = [
  "hoodwink",
  "dawnbreaker",
  "death-prophet",
  "drow-ranger",
  "snapfire",
];
const negativeDire = ["chen", "enigma", "bane", "naga-siren", "mirana"];

function assertJsonParity(actual, expected, path = "$") {
  if (typeof expected === "number") {
    assert.equal(typeof actual, "number", `${path} must be numeric`);
    assert.ok(
      Math.abs(actual - expected) <= 1e-15,
      `${path}: ${actual} differs from Python ${expected}`,
    );
    return;
  }
  if (Array.isArray(expected)) {
    assert.ok(Array.isArray(actual), `${path} must be an array`);
    assert.equal(actual.length, expected.length, `${path} length differs`);
    expected.forEach((item, index) =>
      assertJsonParity(actual[index], item, `${path}[${index}]`),
    );
    return;
  }
  if (expected !== null && typeof expected === "object") {
    assert.ok(
      actual !== null && typeof actual === "object" && !Array.isArray(actual),
      `${path} must be an object`,
    );
    assert.deepEqual(
      Object.keys(actual).sort(),
      Object.keys(expected).sort(),
      `${path} keys differ`,
    );
    for (const [key, value] of Object.entries(expected)) {
      assertJsonParity(actual[key], value, `${path}.${key}`);
    }
    return;
  }
  assert.equal(actual, expected, `${path} differs`);
}

test("serves canonical frontend source with deployment-only social metadata", async () => {
  const [htmlResponse, cssResponse, jsResponse, html, css, javascript] =
    await Promise.all([
      fetchWorker("/"),
      fetchWorker("/static/styles.css"),
      fetchWorker("/static/app.js"),
      readFile(
        new URL("../../src/draft_ai_assistant/web/index.html", import.meta.url),
        "utf8",
      ),
      readFile(
        new URL("../../src/draft_ai_assistant/web/styles.css", import.meta.url),
        "utf8",
      ),
      readFile(
        new URL("../../src/draft_ai_assistant/web/app.js", import.meta.url),
        "utf8",
      ),
    ]);

  assert.equal(htmlResponse.status, 200);
  assert.equal(cssResponse.status, 200);
  assert.equal(jsResponse.status, 200);
  const renderedHtml = await htmlResponse.text();
  assert.ok(renderedHtml.startsWith(html.slice(0, html.indexOf("  </head>"))));
  assert.ok(renderedHtml.endsWith(html.slice(html.indexOf("  </head>"))));
  assert.match(
    renderedHtml,
    /<meta property="og:image" content="http:\/\/draft-lab\.test\/og\.png">/,
  );
  assert.match(
    renderedHtml,
    /<meta property="og:url" content="http:\/\/draft-lab\.test\/">/,
  );
  assert.match(renderedHtml, /name="twitter:card" content="summary_large_image"/);
  assert.equal(await cssResponse.text(), css);
  assert.equal(await jsResponse.text(), javascript);
  assert.match(
    htmlResponse.headers.get("content-security-policy") ?? "",
    /connect-src 'self'/,
  );
});

test("serves the packaged social preview through the asset binding", async () => {
  const image = await readFile(new URL("../public/og.png", import.meta.url));
  const response = await fetchWorker(
    "/og.png",
    {},
    {
      ASSETS: {
        async fetch() {
          return new Response(image, {
            headers: { "content-type": "image/png" },
          });
        },
      },
    },
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "image/png");
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), image);
});

test("mirrors the frozen health, hero, and model-card contracts", async () => {
  for (const [path, expected] of [
    ["/api/v1/health", golden.health],
    ["/api/v1/heroes", golden.heroes],
    ["/api/v1/model-card", golden.model_card],
  ]) {
    const response = await fetchWorker(path);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), expected);
  }
});

test("matches Python analysis to floating-point precision and ignores slot order", async () => {
  const response = await fetchWorker("/api/v1/analyze", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      radiant_picks: radiant,
      dire_picks: dire,
    }),
  });
  const permuted = await fetchWorker("/api/v1/analyze", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      radiant_picks: [...radiant].reverse(),
      dire_picks: [...dire].reverse(),
    }),
  });

  assert.equal(response.status, 200);
  assert.equal(permuted.status, 200);
  const payload = await response.json();
  const permutedPayload = await permuted.json();
  assertJsonParity(payload, golden.analysis);
  assertJsonParity(permutedPayload, golden.permuted_analysis);
  assert.equal(payload.prediction_id, golden.analysis.prediction_id);
  assert.equal(
    permutedPayload.prediction_id,
    golden.permuted_analysis.prediction_id,
  );
  assert.deepEqual(golden.analysis, golden.permuted_analysis);
});

test("matches Python user-directed replacement comparison exactly", async () => {
  const response = await fetchWorker(
    "/api/v1/replacement-comparisons",
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        radiant_picks: radiant,
        dire_picks: dire,
        side: "radiant",
        hero_to_replace: "axe",
        replacement_hero: "abaddon",
      }),
    },
  );

  assert.equal(response.status, 200);
  const payload = await response.json();
  assertJsonParity(payload, golden.replacement);
  assert.equal(payload.comparison_id, golden.replacement.comparison_id);
  assert.equal(payload.recommendation, false);
  assert.equal(
    payload.interpretation,
    "associative_model_comparison_not_causal",
  );
});

test("matches Python negative-logit and Dire-side replacement branches", async () => {
  const analysisResponse = await fetchWorker("/api/v1/analyze", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      radiant_picks: negativeRadiant,
      dire_picks: negativeDire,
    }),
  });
  const replacementResponse = await fetchWorker(
    "/api/v1/replacement-comparisons",
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        radiant_picks: negativeRadiant,
        dire_picks: negativeDire,
        side: "dire",
        hero_to_replace: "chen",
        replacement_hero: "abaddon",
      }),
    },
  );

  assert.equal(analysisResponse.status, 200);
  assert.equal(replacementResponse.status, 200);
  const analysis = await analysisResponse.json();
  const replacement = await replacementResponse.json();
  assertJsonParity(analysis, golden.negative_analysis);
  assertJsonParity(replacement, golden.dire_replacement);
  assert.equal(analysis.probability.favored_side, "dire");
  assert.ok(analysis.explanation.draft_log_odds < 0);
  assert.equal(
    replacement.delta.selected_side_win,
    replacement.delta.dire_win,
  );
  assert.equal(
    replacement.comparison_id,
    golden.dire_replacement.comparison_id,
  );
});

test("preserves the stable unsupported-hero response", async () => {
  const response = await fetchWorker("/api/v1/analyze", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      radiant_picks: ["brand-new-hero", ...radiant.slice(1)],
      dire_picks: dire,
    }),
  });

  assert.equal(response.status, 422);
  assert.deepEqual(await response.json(), golden.unsupported);
});

test("strictly rejects extras, duplicates, and invalid replacement input", async () => {
  const requests = [
    {
      path: "/api/v1/analyze",
      body: {
        radiant_picks: radiant,
        dire_picks: dire,
        first_pick: "radiant",
      },
    },
    {
      path: "/api/v1/analyze",
      body: {
        radiant_picks: ["axe", "axe", ...radiant.slice(2)],
        dire_picks: dire,
      },
    },
    {
      path: "/api/v1/replacement-comparisons",
      body: {
        radiant_picks: radiant,
        dire_picks: dire,
        side: "radiant",
        hero_to_replace: "lina",
        replacement_hero: "abaddon",
      },
    },
  ];

  for (const request of requests) {
    const response = await fetchWorker(request.path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request.body),
    });
    assert.equal(response.status, 422);
    const payload = await response.json();
    assert.equal(payload.detail.code, "invalid_request");
  }
});

test("matches FastAPI method-not-allowed behavior on known API routes", async () => {
  for (const [method, path, allowed] of [
    ["POST", "/api/v1/health", "GET"],
    ["GET", "/api/v1/analyze", "POST"],
    ["PUT", "/api/v1/replacement-comparisons", "POST"],
  ]) {
    const response = await fetchWorker(path, { method });
    assert.equal(response.status, 405);
    assert.equal(response.headers.get("allow"), allowed);
    assert.deepEqual(await response.json(), {
      detail: "Method Not Allowed",
    });
  }
});

test("build packages credential-free hosting metadata", async () => {
  const [source, packaged] = await Promise.all([
    readFile(new URL(".openai/hosting.json", siteRoot), "utf8"),
    readFile(new URL("dist/.openai/hosting.json", siteRoot), "utf8"),
  ]);
  const sourceMetadata = JSON.parse(source);
  assert.deepEqual(JSON.parse(packaged), sourceMetadata);
  assert.equal(sourceMetadata.d1, null);
  assert.equal(sourceMetadata.r2, null);
  if ("project_id" in sourceMetadata) {
    assert.equal(typeof sourceMetadata.project_id, "string");
    assert.ok(sourceMetadata.project_id.length > 0);
  }
  assert.doesNotMatch(
    `${source}\n${packaged}`.toLowerCase(),
    /api[_-]?key|secret|credential|token/,
  );
});
