import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = (process.env.BASE_URL || "http://127.0.0.1:8765").replace(/\/$/, "");
const PREVIEW = process.env.PREVIEW_PATH || "/preview";
const PROJECT = process.env.PROJECT || process.cwd();
const SHOTS = path.join(PROJECT, "artifacts", "screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

const fails = [];
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1920, height: 1200 } });
const page = await context.newPage();

const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(e.message));

const url = `${BASE}${PREVIEW}`;
console.log(`Navigating to ${url}...`);
const resp = await page.goto(url, { waitUntil: "domcontentloaded" });
if (!resp || resp.status() >= 400) {
  console.error(`FAIL: preview page returned HTTP ${resp ? resp.status() : "n/a"} at ${url}`);
  await browser.close();
  process.exit(1);
}

await page.waitForTimeout(3000);

// Check rendered iframes
const expected = await page.$$eval("iframe[data-target-width]", (els) =>
  els.map((e) => ({ device: e.getAttribute("data-device"), want: Number(e.getAttribute("data-target-width")) }))
);
const frames = page.frames().filter((f) => f !== page.mainFrame());
console.log(`iframes rendered: ${frames.length} (expected ${expected.length})`);
if (!frames.length) fails.push("no iframes rendered");

const seenWidths = [];
for (const f of frames) {
  try {
    const info = await f.evaluate(() => ({
      w: window.innerWidth,
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
      pathname: location.pathname,
      textLen: (document.body && document.body.innerText ? document.body.innerText.length : 0),
    }));
    seenWidths.push(info.w);
    const overflow = info.scrollW > info.clientW + 2;
    const blank = info.textLen < 30;
    const status = overflow || blank ? "WARN" : "OK";
    console.log(
      `  [${status}] ${String(info.w).padStart(4)}px  path=${info.pathname}  ` +
      `textLen=${info.textLen}  scrollW=${info.scrollW} clientW=${info.clientW}` +
      `${overflow ? "  <-- HORIZONTAL OVERFLOW" : ""}${blank ? "  <-- BLANK FRAME" : ""}`
    );
  } catch (e) {
    console.log(`  FAIL frame eval: ${e.message}`);
  }
}

// Check shell geometry
const geo = await page.evaluate(() => {
  const out = [];
  document.querySelectorAll(".device").forEach((dev) => {
    const header = dev.querySelector(".device-header");
    const spacer = dev.querySelector("div[style*='position: relative']");
    const shell = spacer && spacer.querySelector(".shell");
    if (!spacer || !shell) return;
    const sp = spacer.getBoundingClientRect();
    const sh = shell.getBoundingClientRect();
    out.push({
      overhang: Math.round(sh.bottom - sp.bottom),
      wOverhang: Math.round(sh.right - sp.right),
    });
  });
  return out;
});

console.log("Geometry checks:", geo);

// Capture screenshot
const screenshotPath = path.join(SHOTS, "ptkit-device-preview.png");
await page.screenshot({ path: screenshotPath, fullPage: true });
console.log(`Screenshot saved to: ${screenshotPath}`);

await browser.close();

if (pageErrors.length > 0) {
  console.error("Page errors occurred:", pageErrors);
  process.exit(1);
}

if (fails.length > 0) {
  console.error("Failures:", fails);
  process.exit(1);
}

console.log("ALL PREVIEW CHECKS PASSED!");
