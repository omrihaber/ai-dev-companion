# Credits & Attribution

This project reuses open-source work (attribution also propagated into finding `sources[]` where applicable):

- [baz-scm/awesome-reviewers](https://github.com/baz-scm/awesome-reviewers) — Apache-2.0 — specialist-agent prompts in `apps/api/src/adc_api/agent_prompts.py` are seeded/adapted from this corpus.
- [Semgrep](https://semgrep.dev) (`semgrep/semgrep` image) + [Bandit](https://github.com/PyCQA/bandit) (`bandit[sarif]`) — Apache-2.0 — external SARIF scanners run as sandboxed-Docker nodes (Inc 5); each finding cites its tool + rule URL.
- [Qodo PR-Agent](https://github.com/qodo-ai/pr-agent) — Apache-2.0 — optional scanner adapter (Inc 5).
- [JSZip](https://stuk.github.io/jszip/) — MIT — browser-side ZIP extraction (folder/zip drag-and-drop normalisation in the web client).
