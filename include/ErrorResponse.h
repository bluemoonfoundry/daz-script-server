#pragma once
#include <string>

// All structured error codes used across the server.
// HTTP status mapping: ErrorResponse::httpStatus().
// Code strings:        ErrorResponse::codeString().
// Default messages:    ErrorResponse::defaultMessage().
enum class ErrorCode {
    // 401 Authentication
    AUTH_MISSING_TOKEN,
    AUTH_INVALID_TOKEN,

    // 403 Authorization
    IP_NOT_WHITELISTED,

    // 404 Not Found
    SCRIPT_NOT_FOUND,
    REQUEST_NOT_FOUND,
    ROUTE_NOT_FOUND,

    // 409 Conflict / 422 Unprocessable
    IDEMPOTENCY_KEY_IN_FLIGHT,
    IDEMPOTENCY_KEY_REUSED,

    // 413 Payload Too Large
    BODY_TOO_LARGE,

    // 429 Too Many Requests
    RATE_LIMIT_EXCEEDED,
    CONCURRENT_LIMIT_EXCEEDED,

    // 400 Bad Request
    BAD_REQUEST,
    INVALID_JSON,
    MISSING_FIELD,
    INVALID_FIELD,
    SCRIPT_TOO_LARGE,
    SCRIPT_FILE_NOT_FOUND,
    SCRIPT_FILE_NOT_FILE,
    SCRIPT_FILE_NOT_ABSOLUTE,
    SCRIPT_FILE_LOAD_FAILED,
    NOT_A_RENDER_REQUEST,
    REQUEST_ALREADY_FINISHED,

    // 503 Service Unavailable
    SERVER_UNAVAILABLE,
    STUDIO_BUSY,

    // 500 Internal Server Error
    INTERNAL_ERROR,

    // Body-only codes: returned inside HTTP 200 execute/job-result bodies
    // (the HTTP exchange succeeded; the script or job did not).
    SCRIPT_ERROR,
    JOB_CANCELLED,
    JOB_STALE,
};

// Builds consistent JSON error responses and maps error codes to HTTP statuses.
//
// Every failure the server reports -- HTTP-level rejections and script/job
// failures alike -- carries the same envelope:
//   {"success":false,"error_code":"CODE","error":"message","retryable":bool}
//   {"success":false,"error_code":"CODE","error":"message","retryable":bool,"detail":"context"}
// Job routes additionally stamp server_instance_id / correlation_id into it.
// `retryable` is true only when an identical retry may succeed without the
// client changing anything (busy, rate limited, queue full, key in flight).
class ErrorResponse {
public:
    // Returns JSON error body. Pass detail for additional context (e.g. the bad field value).
    static std::string build(ErrorCode code, const std::string& detail = "");

    // Fields only (no braces), for embedding the error envelope in a larger
    // object such as a job result: "error_code":"..","error":"..","retryable":..
    // Pass message to override the default message (e.g. a script's own error).
    static std::string fields(ErrorCode code, const std::string& message = "");

    // True when retrying the identical request may succeed.
    static bool retryable(ErrorCode code);

    // HTTP status code for the given error (401/403/404/400/413/429/503).
    static int httpStatus(ErrorCode code);

    // SCREAMING_SNAKE_CASE string identifier for the code (stable, API-visible).
    static const char* codeString(ErrorCode code);

    // Short human-readable message for the code.
    static const char* defaultMessage(ErrorCode code);

    static std::string jsonEscape(const std::string& s);
};
