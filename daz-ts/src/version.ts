/**
 * Plugin version compatibility check, the counterpart of dazpy's
 * `MIN_SERVER_VERSION`. Unlike dazpy, daz-ts never checks on its own: call
 * {@link DazClient.checkServerVersion} when you want to know.
 */

/**
 * Oldest DazScriptServer plugin (major.minor) this daz-ts needs. 2.11 added
 * `/capabilities`, the artifact routes, and `cancel_requested` cancellation,
 * all of which `DazClient` uses. Raise it only when daz-ts starts calling a
 * plugin route or field that older plugins lack.
 */
export const MIN_SERVER_VERSION = "2.11";

const RELEASES_URL = "https://github.com/bluemoonfoundry/daz-script-server/releases";

/** Result of one plugin version check. */
export interface VersionCheck {
  /** Base URL of the checked plugin, e.g. `"http://127.0.0.1:18811"`. */
  serverUrl: string;
  /** Plugin version from `GET /status`; `null` if it didn't report one. */
  serverVersion: string | null;
  /** {@link MIN_SERVER_VERSION} at check time. */
  minServerVersion: string;
  /** The plugin's per-run identity, if it reported one. */
  serverInstanceId: string | null;
  /** `true`/`false`; `null` when a version couldn't be parsed. */
  compatible: boolean | null;
  /** Upgrade advice when `compatible` is `false`, else `null`. */
  message: string | null;
}

/** Return `[major, minor]` from a version string like `"2.10.0"` or `"v2.11"`, or `null`. */
export function parseVersion(value: unknown): [number, number] | null {
  if (typeof value !== "string") return null;
  const m = /^\s*v?(\d+)\.(\d+)/.exec(value);
  return m ? [Number(m[1]), Number(m[2])] : null;
}

/** Compare the version a `/status` body reports against {@link MIN_SERVER_VERSION}. */
export function evaluateServerVersion(serverUrl: string, status: unknown): VersionCheck {
  const body = typeof status === "object" && status !== null ? (status as Record<string, unknown>) : {};
  const serverVersion = typeof body.version === "string" ? body.version : null;
  const instance = body.server_instance_id;
  const serverInstanceId = typeof instance === "string" && instance ? instance : null;

  const server = parseVersion(serverVersion);
  const needed = parseVersion(MIN_SERVER_VERSION);
  const compatible =
    server === null || needed === null ? null : server[0] > needed[0] || (server[0] === needed[0] && server[1] >= needed[1]);
  const message =
    compatible === false
      ? `Daz Studio plugin at ${serverUrl} is version ${serverVersion}; daz-ts needs ` +
        `${MIN_SERVER_VERSION} or newer. Upgrade the DazScriptServer plugin in the ` +
        `Daz Studio instance at that address (${RELEASES_URL}).`
      : null;

  return { serverUrl, serverVersion, minServerVersion: MIN_SERVER_VERSION, serverInstanceId, compatible, message };
}
