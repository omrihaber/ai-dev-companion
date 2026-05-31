import http from "k6/http";
import { check, sleep } from "k6";

export const options = { vus: 10, duration: "30s" };

export default function () {
  const res = http.post("http://localhost:8001/api/reviews",
    JSON.stringify({ language: "python", code: "x=1\n" }),
    { headers: { "Content-Type": "application/json" } });
  check(res, { "status 202": (r) => r.status === 202 });
  sleep(1);
}
