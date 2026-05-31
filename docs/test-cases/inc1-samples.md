# Inc 1 — Sample Test Cases & Expected Output

> Expected outputs describe the *categories and key findings* a capable model returns.
> Exact wording varies (especially with the local default model); tests assert on schema + categories, not phrasing.

## 1. Python — SQL injection (from the assignment)
```python
def get_user_data(user_id):
    query = "SELECT * FROM users WHERE id = " + str(user_id)
    cursor.execute(query)
    return cursor.fetchall()
```
**Expected:** Security/high — SQL injection (use parameterized queries) · Quality/low — missing type hints & docstring · Performance/low — use `fetchone()` if a single row is expected.

## 2. TypeScript — unsafe any + missing await
```typescript
async function load(id) {
  const res = fetch("/api/users/" + id);
  return res.json();
}
```
**Expected:** Logic/high — missing `await` on `fetch` (`res` is a Promise) · Quality/medium — parameter `id` untyped · Security/low — unsanitized id in URL.

## 3. Java — resource leak
```java
public String read(String path) throws Exception {
  BufferedReader r = new BufferedReader(new FileReader(path));
  return r.readLine();
}
```
**Expected:** Logic/high — reader never closed (use try-with-resources) · Style/low — broad `throws Exception` · Security/low — path not validated (path traversal).

---
