# Skill: Adding a language
1. Add an entry to `LANGUAGES` in `packages/core/src/adc_core/sanitization.py` mapping the language id to its tree-sitter grammar name.
2. Add a fixture + test in `packages/core/tests/test_syntax.py` asserting a known syntax error is detected.
3. Add the language to the frontend dropdown in `apps/web/src/components/Workspace.tsx`.
4. Run `task test:py` and `task test:web`.
