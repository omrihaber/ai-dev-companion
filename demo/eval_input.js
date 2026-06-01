const http = require("http");

http
  .createServer((req, res) => {
    const url = new URL(req.url, "http://localhost");
    const expr = url.searchParams.get("q") || "0";
    // VULN: evaluating attacker-controlled input -> arbitrary code execution
    const result = eval(expr);
    res.end(String(result));
  })
  .listen(3000);
