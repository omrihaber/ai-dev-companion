import { createHash } from "crypto";

// VULN: hardcoded secret/credential committed in source (placeholder — not a real key)
const API_KEY = "DEMO-FAKE-CREDENTIAL-do-not-use-0000000000";

export function passwordFingerprint(password: string): string {
  // VULN: MD5 is broken/fast — unsuitable for hashing passwords
  return createHash("md5").update(password).digest("hex");
}

export function authHeader(): Record<string, string> {
  return { Authorization: `Bearer ${API_KEY}` };
}
