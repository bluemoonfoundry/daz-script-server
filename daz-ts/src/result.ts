/** The result of a synchronous or asynchronous DazScript execution. */
export interface ExecutionResult {
  /** The return value of the script (JSON-decoded). */
  value: unknown;
  /** Lines written to the DAZ Studio message log during execution. */
  output: string[];
  /** The server-assigned request ID (empty for sync executions). */
  requestId: string;
  /** `true` if the script completed without error. */
  success: boolean;
  /** Error message returned by the server (empty when successful). */
  error: string;
  /** Wall-clock execution time in milliseconds as measured by the server. */
  durationMs: number;
}
