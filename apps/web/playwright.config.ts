import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://localhost:5173" },
  webServer: [
    {
      command: "ADC_MODEL_PROVIDER=mock ADC_BACKEND=memory uv run --project ../../apps/api uvicorn adc_api.main:app --port 8001",
      url: "http://localhost:8001/api/health",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "VITE_API_BASE_URL=http://localhost:8001 pnpm dev --port 5173",
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
