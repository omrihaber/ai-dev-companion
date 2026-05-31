# Skill: Adding a model provider
1. Implement the `ModelProvider` protocol (`name`, `model`, `async review(code, language) -> list[RawFinding]`) in `apps/api/src/adc_api/providers.py`.
2. Register it in `build_provider()` keyed by `ADC_MODEL_PROVIDER`.
3. Add a unit test using recorded output (never a live call).
