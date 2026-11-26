/** Internal timing helper shared by the SDK. Not part of the public API. */

/** Resolve after `ms` milliseconds. Callers holding seconds must convert explicitly (`s * 1000`). */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
