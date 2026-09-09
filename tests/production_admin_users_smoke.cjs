const path = require("node:path");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on("console", (message) => message.type() === "error" && errors.push(message.text()));
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("https://aquanotes.farlabs.my.id/login");
    await page.getByLabel("Email").fill(process.env.TEST_EMAIL);
    await page.getByLabel("Password", { exact: true }).fill(process.env.TEST_PASSWORD);
    await page.getByRole("button", { name: "Masuk", exact: true }).click();
    await page.waitForURL("**/admin");
    await page.getByRole("link", { name: "Daftar user" }).click();
    await page.getByRole("heading", { name: "Daftar user" }).waitFor();
    await page.getByText("Total akun", { exact: true }).waitFor();
    await page.getByLabel("Filter akses").selectOption("admin");
    await page.getByRole("button", { name: "Terapkan" }).click();
    await page.waitForURL("**/admin/users?role=admin");
    await page.getByText("Administrator", { exact: true }).first().waitFor();
    await page.screenshot({ path: path.join(process.env.PW_ARTIFACT_DIR, "admin-users-desktop.png"), fullPage: true });
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("https://aquanotes.farlabs.my.id/admin/users");
    await page.getByRole("heading", { name: "Daftar user" }).waitFor();
    if (await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)) throw new Error("Halaman mobile overflow horizontal");
    await page.screenshot({ path: path.join(process.env.PW_ARTIFACT_DIR, "admin-users-mobile.png"), fullPage: true });
    if (errors.length) throw new Error(errors.join(" | "));
    console.log("production_admin_users=ok");
  } finally {
    await browser.close();
  }
})();
