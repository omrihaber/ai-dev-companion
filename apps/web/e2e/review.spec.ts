import { expect, test } from "@playwright/test";

test("submit code, watch progress, see categorized cited findings, jump to line", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("language").selectOption("python");
  await page.getByRole("button", { name: /Review Code/ }).click();

  // progress stepper advances to done
  await expect(page.getByRole("status", { name: /review progress/ })).toContainText("done", { timeout: 30000 });

  // categorized + cited finding appears
  await expect(page.getByText("SQL injection vulnerability").first()).toBeVisible();
  await expect(page.getByText(/security/i).first()).toBeVisible();
  await expect(page.getByText(/security-agent/)).toBeVisible();

  // click-to-jump does not error
  await page.getByRole("button", { name: /line 2/ }).first().click();
});
