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

    // 413 Payload Too Large
    BODY_TOO_LARGE,

    // 429 Too Many Requests
    RATE_LIMIT_EXCEEDED,
    CONCURRENT_LIMIT_EXCEEDED,

    // 400 Bad Request
    INVALID_JSON,
    MISSING_FIELD,
    INVALID_FIELD,
    SCRIPT_TOO_LARGE,
    SCRIPT_FILE_NOT_FOUND,
    SCRIPT_FILE_NOT_FILE,
    SCRIPT_FILE_NOT_ABSOLUTE,
    SCRIPT_FILE_LOAD_FAILED,

    // 503 Service Unavailable
    SERVER_UNAVAILABLE,
    STUDIO_BUSY,

    // 500 Internal Server Error
    INTERNAL_ERROR,
};

// Builds consistent JSON error responses and maps error codes to HTTP statuses.
//
// Response format:
//   {"success":false,"error_code":"CODE","error":"message"}
//   {"success":false,"error_code":"CODE","error":"message","detail":"context"}
class ErrorResponse {
public:
    // Returns JSON error body. Pass detail for additional context (e.g. the bad field value).
    static std::string build(ErrorCode code, const std::string& detail = "");

    // HTTP status code for the given error (401/403/404/400/413/429/503).
    static int httpStatus(ErrorCode code);

    // SCREAMING_SNAKE_CASE string identifier for the code (stable, API-visible).
    static const char* codeString(ErrorCode code);

    // Short human-readable message for the code.
    static const char* defaultMessage(ErrorCode code);

private:
    static std::string jsonEscape(const std::string& s);
};
