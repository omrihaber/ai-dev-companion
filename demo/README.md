# Demo snippets

A small set of intentionally-vulnerable files (one per supported language) for showcasing the reviewer.
Each file has a clearly planted issue (marked `VULN`/`BUG` in a comment) so the output is predictable.

## How to use
- **Snippet tab:** open a file, pick the matching **language**, paste its contents, **Review Code**.
- **Project tab:** drag this whole `demo/` folder onto the left pane (or use 📁 Folder). The file tree
  appears; mark the files you want the agents to deep-review and hit **Review**. The scanners (Semgrep on
  most languages, Bandit on Python) cover everything; the LLM agents deep-review your marked files.

> **Note on determinism:** the exact wording/severity from the LLM agents varies by model. The
> **category** and the **issue itself** are the stable expectation. Scanner citations (🔧 Semgrep/Bandit)
> are deterministic where a rule matches. With `ADC_SCANNERS=` or no Docker, you'll see agent (🤖) sources only.

## Expected findings

| File | Lang | Planted issue | Expected finding(s) — category · severity | Likely sources |
|---|---|---|---|---|
| `sql_injection.py` | Python | User input concatenated into SQL | **SQL injection** · security · high–critical | 🤖 security-agent · 🔧 bandit (B608) · 🔧 semgrep |
| `eval_input.js` | JavaScript | `eval()` on a request param | **Code injection via eval** · security · high–critical | 🤖 security-agent · 🔧 semgrep |
| `secrets_weak_hash.ts` | TypeScript | Hardcoded API key + MD5 for passwords | **Hardcoded secret** · security · high; **Weak hash (MD5)** · security · medium–high | 🤖 security-agent · 🔧 semgrep (where matched) |
| `CommandInjection.java` | Java | User input in `Runtime.exec` | **Command injection** · security · high–critical | 🤖 security-agent · 🔧 semgrep |
| `path_traversal.go` | Go | User input in a file path + ignored error | **Path traversal** · security · high; **Ignored error** · logic/quality · low–medium | 🤖 security-agent · 🤖 logic-agent · 🔧 semgrep |
| `unwrap_overflow.rs` | Rust | `unwrap()` panics + `u8` overflow | **Panic on unwrap / missing error handling** · logic–quality · medium; **Integer overflow** · logic · low–medium | 🤖 logic-agent · 🤖 quality-agent (Rust isn't scanner-covered here) |
| `unsafe_backup.sh` | Bash | `eval` on input + unquoted `rm -rf` | **Command injection** · security · high; **Unquoted variable / dangerous `rm`** · quality–security · medium | 🤖 security-agent · 🤖 quality-agent · 🔧 semgrep (where matched) |

A multi-source card (e.g. the Python SQL injection cited by 🤖 `security-agent` **+** 🔧 `bandit` **+**
🔧 `semgrep`) is the headline behavior to look for — that's the aggregator merging duplicate findings and
unioning their `sources[]`.

## Coverage notes
- **Semgrep** (`--config auto`) covers Python, JS/TS, Java, Go and more; **Bandit** covers Python only.
- **tree-sitter** also runs on every file and reports real **syntax** errors (these snippets are all valid,
  so expect none).
- Each snippet also includes a safe/benign counterpart or comment so the contrast is visible in the diff.
