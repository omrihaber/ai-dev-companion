import { expect, test } from "@playwright/test";

// The simple single-snippet flow (assignment requirement): default Snippet tab + language dropdown.
test("snippet review: pick language, watch progress, see categorized cited findings, jump to line", async ({ page }) => {
  await page.goto("/");
  // language picker is a custom dropdown (renders real logos); pick python explicitly
  await page.getByRole("button", { name: "language" }).click();
  await page.getByRole("option", { name: "python" }).click();
  await page.getByRole("button", { name: /Review Code/ }).click();

  // progress stepper advances to done
  await expect(page.getByRole("status", { name: /review progress/ })).toContainText("done", { timeout: 30000 });

  // categorized + cited finding appears
  await expect(page.getByText("SQL injection vulnerability").first()).toBeVisible();
  await expect(page.getByText(/security/i).first()).toBeVisible();
  await expect(page.getByText(/security-agent/)).toBeVisible();

  // click-to-jump: the FindingCard renders a <button class="loc"> with text "line N ↗"
  await page.locator(".loc").first().click();
});
