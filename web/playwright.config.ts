import { defineConfig } from "@playwright/test";

const reuse = !process.env.CI;

// Fixture mode end to end: the API answers from tests/fixtures, the web app is a production build pointed at it.
export default defineConfig({
  testDir: "e2e",
  use: { channel: "chrome", baseURL: "http://127.0.0.1:3765" },
  webServer: [
    {
      command: "cd .. && SHERPA_UI_FIXTURES=1 uv run uvicorn app.api:app --host 127.0.0.1 --port 8765",
      url: "http://127.0.0.1:8765/api/health",
      reuseExistingServer: reuse,
    },
    {
      command:
        "SHERPA_API_URL=http://127.0.0.1:8765 pnpm build && SHERPA_API_URL=http://127.0.0.1:8765 pnpm start -p 3765",
      url: "http://127.0.0.1:3765",
      reuseExistingServer: reuse,
      timeout: 300_000,
    },
  ],
});
