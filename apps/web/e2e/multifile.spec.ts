import { expect, test } from "@playwright/test";
import JSZip from "jszip";

test("multi-file review: coverage banner, per-file findings, re-run", async ({ page }) => {
  await page.goto("/");

  // Build a zip containing two Python files in-process.
  const zip = new JSZip();
  zip.file("auth.py", 'q = "SELECT * FROM users WHERE id=" + uid\ncursor.execute(q)\n');
  zip.file("util.py", "x = 1\n");
  const zipBuffer = await zip.generateAsync({ type: "nodebuffer" });

  // Upload via the .zip picker (stable selector regardless of button order).
  await page.locator('input[accept=".zip"]').setInputFiles([
    { name: "upload.zip", mimeType: "application/zip", buffer: zipBuffer },
  ]);

  await page.getByRole("button", { name: /Review .* file/ }).click();

  // Coverage banner appears when the review is done (both files agent-reviewed under mock).
  await expect(page.locator(".coverage-banner")).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".coverage-banner")).toContainText("/ 2");

  // Re-run button is present.
  await expect(page.locator(".rerun-btn")).toBeVisible();

  // Switch active file to util.py via the tree-file button.
  await page.getByRole("button", { name: "util.py" }).click();
});
