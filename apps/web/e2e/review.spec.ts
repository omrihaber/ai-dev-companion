import { expect, test } from "@playwright/test";

test("submit code, watch progress, see categorized cited findings, jump to line", async ({ page }) => {
  await page.goto("/");

  // Default sample (snippet.py) is already loaded and marked — just click Review.
  await page.getByRole("button", { name: /Review .* file/ }).click();

  // progress stepper advances to done
  await expect(page.getByRole("status", { name: /review progress/ })).toContainText("done", { timeout: 30000 });

  // categorized + cited finding appears
  await expect(page.getByText("SQL injection vulnerability").first()).toBeVisible();
  await expect(page.getByText(/security/i).first()).toBeVisible();
  await expect(page.getByText(/security-agent/)).toBeVisible();

  // click-to-jump: the FindingCard renders a <button class="loc"> with text "line N ↗"
  await page.locator(".loc").first().click();
});
