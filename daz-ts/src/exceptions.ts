/** Base class for all daz-ts exceptions. */
export class DazError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/** Raised when the SDK cannot reach the DAZ Studio Script Server. */
export class ConnectionError extends DazError {}

/** Raised on HTTP 401 or 403 (bad or missing API token, or IP blocked). */
export class AuthenticationError extends DazError {}

/**
 * Base class for transient "DAZ Studio is busy, please retry" conditions.
 */
export class DazBusyError extends DazError {
  /** Human-readable explanation of why the server is busy. */
  readonly reason: string;
  /** Server-suggested seconds to wait before retrying. */
  readonly retryAfter: number;

  constructor(message: string, reason = "", retryAfter = 2.0) {
    super(message);
    this.reason = reason;
    this.retryAfter = retryAfter;
  }
}

/**
 * Raised on HTTP 503 STUDIO_BUSY: DAZ Studio's main thread is occupied
 * with a scene load, save, clear, or render and cannot service the request.
 */
export class StudioBusyError extends DazBusyError {}

/**
 * Raised on HTTP 429 CONCURRENT_LIMIT_EXCEEDED: too many requests are
 * already in flight against the server.
 */
export class ConcurrencyLimitError extends DazBusyError {}

/** Base class for errors that originate inside a DazScript execution. */
export class ScriptError extends DazError {
  /** The DazScript source that was submitted (may be empty for file-based executions). */
  readonly script: string;
  /** The server-assigned request ID, useful for log correlation. */
  readonly requestId: string;
  /** Lines written to the DAZ Studio message log before the error. */
  readonly output: string[];

  constructor(message: string, script = "", requestId = "", output: string[] = []) {
    super(message);
    this.script = script;
    this.requestId = requestId;
    this.output = output;
  }

  /** A formatted string with line-numbered source and error details. */
  get diagnostic(): string {
    const lines: string[] = [];
    if (this.script) {
      const numbered = this.script
        .split("\n")
        .map((line, i) => `${String(i + 1).padStart(4, " ")}: ${line}`)
        .join("\n");
      lines.push(numbered);
    }
    lines.push(this.message);
    if (this.output.length > 0) {
      lines.push("\nCaptured output:\n" + this.output.join("\n"));
    }
    if (this.requestId) {
      lines.push(`request_id: ${this.requestId}`);
    }
    return lines.join("\n");
  }
}

/** Raised when the DazScript engine reports a parse / syntax error. */
export class ScriptSyntaxError extends ScriptError {}

/** Raised when a DazScript execution fails at runtime (TypeError, ReferenceError, etc.). */
export class ScriptRuntimeError extends ScriptError {}

/**
 * Raised when an HTTP request or async poll exceeds its timeout.
 *
 * Named `DazTimeoutError` (not `TimeoutError`) to avoid shadowing the
 * platform's built-in exception name.
 */
export class DazTimeoutError extends DazError {}

/** Raised when a requested scene node, bone, or skeleton cannot be found. */
export class NodeNotFoundError extends DazError {}

/**
 * Raised when an async request fails, is cancelled, or times out while polling.
 */
export class AsyncExecutionError extends DazError {
  /** The server-assigned request ID of the failed async job. */
  readonly requestId: string;

  constructor(message: string, requestId = "") {
    super(message);
    this.requestId = requestId;
  }
}

/** Raised when a render job fails on the DAZ Studio side. */
export class RenderError extends DazError {
  /** The server-assigned render request ID. */
  readonly requestId: string;

  constructor(message: string, requestId = "") {
    super(message);
    this.requestId = requestId;
  }
}

/**
 * Raised by {@link Batch.execute} (or `addOperation`, for the operation-count
 * limit) when a batch would exceed its configured operation-count or
 * generated-script-length limit.
 *
 * Raised client-side before any HTTP call, so an oversized batch never
 * reaches Studio's main thread.
 */
export class BatchLimitExceededError extends DazError {}

/**
 * Raised when an Iray material/surface-property operation fails.
 *
 * Covers a missing material, a channel label that doesn't resolve to a
 * property on the live material, or a failed `setValue()`/`setMap()`.
 */
export class MaterialError extends DazError {
  /** The server-assigned render request ID. */
  readonly requestId: string;

  constructor(message: string, requestId = "") {
    super(message);
    this.requestId = requestId;
  }
}
