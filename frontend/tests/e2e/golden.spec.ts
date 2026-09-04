import { test, expect } from "@playwright/test";

// Golden flow (docs/ARCHITECTURE.md §33, §38): register/sign in -> create KB ->
// upload a fixture doc -> wait for `ready` -> ask a question -> assert a cited
// answer renders with a source in the panel.
//
// Assumes the API is reachable at the same origin (dev proxy or nginx) with the
// CI profile (fake providers). A unique email per run keeps it idempotent.

const stamp = Date.now();
const EMAIL = `e2e+${stamp}@example.com`;
const PASSWORD = "e2e-password-123";
const KB_NAME = `E2E Handbook ${stamp}`;

const FIXTURE = `# Employee Handbook

## Time off
Full-time employees receive 25 days of paid annual leave per year,
accrued monthly. Unused leave up to 5 days may be carried over.

## Code of conduct
Harassment of any kind results in disciplinary action up to termination.
`;

test("golden: upload a document and get a cited answer", async ({ page }) => {
  await page.goto("/login");

  // register (first user becomes admin; if the instance already has users and
  // open registration is off this still works for the very first CI run)
  await page.getByRole("button", { name: "Register" }).click();
  await page.getByLabel("Display name").fill("E2E Bot");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: /Register & sign in/ }).click();

  await expect(page).toHaveURL(/knowledge-bases/);

  // create a KB
  await page.getByLabel("Name").fill(KB_NAME);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByText(KB_NAME)).toBeVisible();

  // open its documents page
  await page
    .locator(".card", { hasText: KB_NAME })
    .getByRole("button", { name: "Documents" })
    .click();
  await expect(page).toHaveURL(/documents/);

  // upload the fixture
  await page.setInputFiles('input[type="file"]', {
    name: "handbook.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(FIXTURE),
  });

  // wait for it to reach ready (SSE + polling backstop)
  await expect(page.getByText("handbook.md")).toBeVisible();
  await expect(page.locator(".pill.ok", { hasText: "ready" })).toBeVisible({ timeout: 45_000 });

  // ask a question
  await page.getByRole("link", { name: "Chat" }).click();
  await page.locator("select").first().selectOption({ label: KB_NAME });
  await page.getByPlaceholder("Ask a question…").fill("How much paid leave do employees get?");
  await page.getByRole("button", { name: "Send" }).click();

  // an assistant answer with at least one citation chip + a source card
  const assistant = page.locator(".msg.assistant").last();
  await expect(assistant.locator("sup.cite").first()).toBeVisible({ timeout: 30_000 });
  await expect(assistant.getByRole("button", { name: "helpful", exact: true })).toBeVisible();
  await expect(page.locator(".sources .source").first()).toBeVisible();
  // the abstention pill must NOT be present on an answerable question
  await expect(assistant.locator(".pill.warn", { hasText: "abstained" })).toHaveCount(0);
});
