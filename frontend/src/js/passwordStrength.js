// Advisory red/yellow/green password meter (PLR-9a, plan §3). Mirrors
// backend/mtg_analyzer/services/password_policy.py `strength` for length and
// character classes; the server stays authoritative and additionally rejects
// blocklisted passwords (reported on submit). No imports: pure, testable in node.

/**
 * @param {string} password
 * @param {{min_length: number, green_length: number}} policy from GET /api/auth/policy
 * @returns {{level: 'red' | 'yellow' | 'green', missing: string[]}}
 *   `missing` lists unmet recommendations: 'length' | 'digit' | 'special'.
 */
export function passwordStrength(password, policy) {
  if ([...password].length < policy.min_length) return { level: 'red', missing: [] };
  const missing = [];
  if ([...password].length < Math.max(policy.green_length, policy.min_length)) missing.push('length');
  if (!/\p{Nd}/u.test(password)) missing.push('digit');
  // Special = neither letter, digit nor whitespace (same as the server's isalnum/isspace test).
  if (!/[^\p{L}\p{N}\s]/u.test(password)) missing.push('special');
  return { level: missing.length ? 'yellow' : 'green', missing };
}
