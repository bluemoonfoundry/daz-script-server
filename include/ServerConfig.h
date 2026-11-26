#pragma once
#include <cstddef>

// ─── Configuration Constants ──────────────────────────────────────────────────
// Every server-wide default, limit and timing constant, in one Qt-free header so
// services (rate limiter, idempotency cache, async manager, settings) can share
// them without pulling in the pane and DAZ SDK headers. Nothing else should
// redefine these values: include this header instead.

namespace ServerConfig {

// Inclusive [min, max] range for a user-configurable setting. The settings pane
// spin boxes, SettingsService::validate() and SettingsService::clampToValid()
// all read the same range, so they can't disagree (README "Configuration").
struct IntRange {
    int min;
    int max;
    constexpr bool contains(int v) const { return v >= min && v <= max; }
};

// ── User-configurable settings: defaults and allowed ranges ──────────────────
constexpr int      DEFAULT_PORT                    = 18811;
constexpr IntRange PORT_RANGE                      = { 1024, 65535 };
constexpr int      DEFAULT_TIMEOUT_SEC             = 30;
constexpr IntRange TIMEOUT_SEC_RANGE               = { 5, 300 };

constexpr int      DEFAULT_MAX_CONCURRENT_REQUESTS = 10;
constexpr IntRange MAX_CONCURRENT_REQUESTS_RANGE   = { 5, 50 };
constexpr int      DEFAULT_MAX_BODY_SIZE_MB        = 5;
constexpr IntRange MAX_BODY_SIZE_MB_RANGE          = { 1, 50 };
constexpr int      DEFAULT_MAX_SCRIPT_LENGTH_KB    = 1024;  // 1MB in KB
constexpr IntRange MAX_SCRIPT_LENGTH_KB_RANGE      = { 100, 10240 };

constexpr int      DEFAULT_RATE_LIMIT_MAX          = 60;
constexpr IntRange RATE_LIMIT_MAX_RANGE            = { 10, 1000 };
constexpr int      DEFAULT_RATE_LIMIT_WINDOW       = 60;    // seconds
constexpr IntRange RATE_LIMIT_WINDOW_RANGE         = { 10, 300 };

// Async request management
constexpr int ASYNC_CLEANUP_INTERVAL_MIN = 5;   // How often to purge TTL-expired async requests
// Default for the "Stuck job timeout" setting (ServerSettings::staleJobTimeoutMin):
// a running request older than this is presumed blocked (e.g. behind a DAZ
// Studio modal) and reported as "stale" so it doesn't poll as "running"
// forever. See failStaleRunning(). Checked every ASYNC_CLEANUP_INTERVAL_MIN,
// so the range minimum matches that interval.
constexpr int      ASYNC_STALE_RUNNING_TIMEOUT_MIN = 30;
constexpr IntRange ASYNC_STALE_RUNNING_TIMEOUT_RANGE_MIN = { ASYNC_CLEANUP_INTERVAL_MIN, 1440 };
// Finished async requests are kept this long (AsyncRequestManager::cleanupExpired()).
constexpr int ASYNC_RESULT_TTL_SEC = 3600;
constexpr int ASYNC_MAX_QUEUE_DEPTH      = 100;
constexpr int ASYNC_MAX_TRACKED_REQUESTS = 1000;
constexpr int ASYNC_LOG_TAIL_LINES       = 100;
constexpr int ASYNC_RESULT_POLL_INTERVAL_MS = 500;  // Long-poll sleep interval in getResultJson()

// Idempotency-Key replay cache. Entries live as long as the async job results
// they replay.
constexpr int       IDEMPOTENCY_MAX_KEY_LENGTH = 255;
constexpr int       IDEMPOTENCY_MAX_ENTRIES    = 1000;
constexpr long long IDEMPOTENCY_TTL_MS         = ASYNC_RESULT_TTL_SEC * 1000LL;

// ── Fixed internal constants ─────────────────────────────────────────────────
constexpr int MAX_LOG_LINES = 1000;
constexpr int MAX_CAPTURED_LINES = 10000;
constexpr int RATE_LIMIT_CLEANUP_INTERVAL = 100;  // requests between rate-limiter sweeps

// Server lifecycle timing
constexpr int PROGRESS_POLL_INTERVAL_MS = 200;      // Main-thread sampling of DzProgress for busy checks
constexpr int SERVER_BIND_WAIT_MS = 100;            // Wait after listen() before checking is_running()
constexpr int SERVER_THREAD_STOP_TIMEOUT_MS = 5000; // Max wait for the listen thread to join on stop/failed bind (then leaked, never terminated)
constexpr int HTTP_KEEP_ALIVE_MAX_COUNT = 5;        // Max requests per persistent connection
constexpr int HTTP_KEEP_ALIVE_TIMEOUT_SEC = 5;      // Keep-alive idle timeout in seconds

// Main-thread crossing: how often a waiting worker re-checks the client socket
// and its deadline (MainThreadCall::post()).
constexpr int MAIN_THREAD_POLL_SLICE_MS = 250;

// SSE streams (/events, render progress). The keepalive interval is also
// the subscriber-queue pop timeout; it must stay well under the HTTP write
// timeout so a keepalive goes out before the stream's wait_writable() check
// can time out.
constexpr int SSE_KEEPALIVE_INTERVAL_MS = 3000;
constexpr int SSE_FRAME_POLL_MS = 500;              // Studio 6 render-progress frame polling
// httplib's default, set explicitly so the SSE relationship above is visible.
constexpr int HTTP_WRITE_TIMEOUT_SEC = 5;
static_assert(SSE_KEEPALIVE_INTERVAL_MS < HTTP_WRITE_TIMEOUT_SEC * 1000,
              "SSE keepalive must go out before the write timeout expires");

// Retry-After header values (seconds, as header strings).
constexpr const char* RETRY_AFTER_BUSY_SEC      = "2";  // 503 STUDIO_BUSY
constexpr const char* RETRY_AFTER_IN_FLIGHT_SEC = "1";  // 409 IDEMPOTENCY_KEY_IN_FLIGHT

// Body-size settings are in MB; httplib and the middleware compare bytes.
inline size_t mbToBytes(int mb) { return static_cast<size_t>(mb) * 1024 * 1024; }

// Per-request limits on the render endpoints (also reported by GET /capabilities)
constexpr int MAX_BATCH_VARIANTS = 100;     // POST /render/batch "variants"
constexpr int MAX_ANIMATION_FRAMES = 1000;  // POST /render/animation frame range

// GET /capabilities document schema. Bump on any breaking change to its shape.
constexpr int CAPABILITIES_SCHEMA_VERSION = 1;

}  // namespace ServerConfig
