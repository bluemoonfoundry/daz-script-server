/** Shared fixtures for the unit tests. */

/** A `Response` carrying `body` as JSON (HTTP 200 unless `status` is given). */
export function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}
