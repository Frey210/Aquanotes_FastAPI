const path = require("node:path");
const { chromium } = require("playwright");

const baseUrl = "https://aquanotes.farlabs.my.id";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on("console", (message) => message.type() === "error" && errors.push(message.text()));
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`${baseUrl}/login`);
    await page.getByLabel("Email").fill(process.env.TEST_EMAIL);
    await page.getByLabel("Password", { exact: true }).fill(process.env.TEST_PASSWORD);
    await page.getByRole("button", { name: "Masuk", exact: true }).click();
    await page.waitForURL("**/admin");
    await page.goto(`${baseUrl}/admin/monitoring`);
    await page.getByRole("heading", { name: "Sensor seluruh perangkat" }).waitFor();
    const row = page.getByRole("row").filter({ hasText: "AQ Selada" });
    await row.waitFor();
    if (await row.getByText("Waktu perangkat tidak sinkron", { exact: true }).count()) {
      throw new Error("Timestamp sensor masih dianggap di masa depan");
    }
    if (errors.length) throw new Error(errors.join(" | "));
    await page.screenshot({
      path: path.join(process.env.PW_ARTIFACT_DIR, "timefix-production-monitoring.png"),
      fullPage: true,
    });
    console.log("production_monitoring=ok");
  } finally {
    await browser.close();
  }
})();
