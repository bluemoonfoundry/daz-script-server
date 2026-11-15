#include "ErrorResponse.h"
#include <cstdio>

const char* ErrorResponse::codeString(ErrorCode code)
{
    switch (code) {
    case ErrorCode::AUTH_MISSING_TOKEN:        return "AUTH_MISSING_TOKEN";
    case ErrorCode::AUTH_INVALID_TOKEN:        return "AUTH_INVALID_TOKEN";
    case ErrorCode::IP_NOT_WHITELISTED:        return "IP_NOT_WHITELISTED";
    case ErrorCode::SCRIPT_NOT_FOUND:          return "SCRIPT_NOT_FOUND";
    case ErrorCode::REQUEST_NOT_FOUND:         return "REQUEST_NOT_FOUND";
    case ErrorCode::ROUTE_NOT_FOUND:           return "ROUTE_NOT_FOUND";
    case ErrorCode::ARTIFACT_NOT_FOUND:        return "ARTIFACT_NOT_FOUND";
    case ErrorCode::ARTIFACT_UNAVAILABLE:      return "ARTIFACT_UNAVAILABLE";
    case ErrorCode::IDEMPOTENCY_KEY_IN_FLIGHT: return "IDEMPOTENCY_KEY_IN_FLIGHT";
    case ErrorCode::IDEMPOTENCY_KEY_REUSED:    return "IDEMPOTENCY_KEY_REUSED";
    case ErrorCode::THUMBNAIL_UNSUPPORTED:     return "THUMBNAIL_UNSUPPORTED";
    case ErrorCode::BODY_TOO_LARGE:            return "BODY_TOO_LARGE";
    case ErrorCode::RATE_LIMIT_EXCEEDED:       return "RATE_LIMIT_EXCEEDED";
    case ErrorCode::CONCURRENT_LIMIT_EXCEEDED: return "CONCURRENT_LIMIT_EXCEEDED";
    case ErrorCode::BAD_REQUEST:               return "BAD_REQUEST";
    case ErrorCode::INVALID_JSON:              return "INVALID_JSON";
    case ErrorCode::MISSING_FIELD:             return "MISSING_FIELD";
    case ErrorCode::INVALID_FIELD:             return "INVALID_FIELD";
    case ErrorCode::SCRIPT_TOO_LARGE:          return "SCRIPT_TOO_LARGE";
    case ErrorCode::SCRIPT_FILE_NOT_FOUND:     return "SCRIPT_FILE_NOT_FOUND";
    case ErrorCode::SCRIPT_FILE_NOT_FILE:      return "SCRIPT_FILE_NOT_FILE";
    case ErrorCode::SCRIPT_FILE_NOT_ABSOLUTE:  return "SCRIPT_FILE_NOT_ABSOLUTE";
    case ErrorCode::SCRIPT_FILE_LOAD_FAILED:   return "SCRIPT_FILE_LOAD_FAILED";
    case ErrorCode::NOT_A_RENDER_REQUEST:      return "NOT_A_RENDER_REQUEST";
    case ErrorCode::REQUEST_ALREADY_FINISHED:  return "REQUEST_ALREADY_FINISHED";
    case ErrorCode::SERVER_UNAVAILABLE:        return "SERVER_UNAVAILABLE";
    case ErrorCode::STUDIO_BUSY:               return "STUDIO_BUSY";
    case ErrorCode::INTERNAL_ERROR:            return "INTERNAL_ERROR";
    case ErrorCode::SCRIPT_ERROR:              return "SCRIPT_ERROR";
    case ErrorCode::JOB_CANCELLED:             return "JOB_CANCELLED";
    case ErrorCode::JOB_STALE:                 return "JOB_STALE";
    default:                                   return "UNKNOWN_ERROR";
    }
}

const char* ErrorResponse::defaultMessage(ErrorCode code)
{
    switch (code) {
    case ErrorCode::AUTH_MISSING_TOKEN:
        return "Authentication required: include 'X-API-Token' header or 'Authorization: Bearer <token>'";
    case ErrorCode::AUTH_INVALID_TOKEN:
        return "Authentication failed: invalid or missing API token";
    case ErrorCode::IP_NOT_WHITELISTED:
        return "Access denied: IP address is not in the whitelist";
    case ErrorCode::SCRIPT_NOT_FOUND:
        return "Script not found in registry";
    case ErrorCode::REQUEST_NOT_FOUND:
        return "Request not found (unknown ID, expired after its TTL, or submitted to a previous server instance)";
    case ErrorCode::ROUTE_NOT_FOUND:
        return "No route matches this method and path";
    case ErrorCode::ARTIFACT_NOT_FOUND:
        return "Artifact not found: the job declared no output with this artifact ID";
    case ErrorCode::ARTIFACT_UNAVAILABLE:
        return "Artifact was declared but its file is missing, not a regular file, or not an absolute path";
    case ErrorCode::IDEMPOTENCY_KEY_IN_FLIGHT:
        return "A request with this Idempotency-Key is still being processed; retry shortly";
    case ErrorCode::IDEMPOTENCY_KEY_REUSED:
        return "This Idempotency-Key was already used on this route with a different request body";
    case ErrorCode::THUMBNAIL_UNSUPPORTED:
        return "No thumbnail can be made for this artifact: it is not an image Qt can decode, or it is too large";
    case ErrorCode::BODY_TOO_LARGE:
        return "Request body exceeds maximum allowed size";
    case ErrorCode::RATE_LIMIT_EXCEEDED:
        return "Rate limit exceeded: too many requests from this IP address, please wait before retrying";
    case ErrorCode::CONCURRENT_LIMIT_EXCEEDED:
        return "Server busy: maximum concurrent requests reached, please retry";
    case ErrorCode::BAD_REQUEST:
        return "Malformed HTTP request";
    case ErrorCode::INVALID_JSON:
        return "Invalid JSON in request body";
    case ErrorCode::MISSING_FIELD:
        return "A required field is missing from the request";
    case ErrorCode::INVALID_FIELD:
        return "A field in the request has an invalid value";
    case ErrorCode::SCRIPT_TOO_LARGE:
        return "Script exceeds maximum allowed length; use 'scriptFile' for large scripts";
    case ErrorCode::SCRIPT_FILE_NOT_FOUND:
        return "Script file not found; verify the path is correct and accessible";
    case ErrorCode::SCRIPT_FILE_NOT_FILE:
        return "Script path points to a directory, not a file";
    case ErrorCode::SCRIPT_FILE_NOT_ABSOLUTE:
        return "Script path must be absolute (e.g. C:/Scripts/file.dsa or /home/user/file.dsa)";
    case ErrorCode::SCRIPT_FILE_LOAD_FAILED:
        return "Failed to load script file";
    case ErrorCode::NOT_A_RENDER_REQUEST:
        return "Not a render request";
    case ErrorCode::REQUEST_ALREADY_FINISHED:
        return "Request already finished";
    case ErrorCode::SERVER_UNAVAILABLE:
        return "Service temporarily unavailable";
    case ErrorCode::STUDIO_BUSY:
        return "DAZ Studio's main thread is busy; please retry shortly";
    case ErrorCode::INTERNAL_ERROR:
        return "An internal server error occurred";
    case ErrorCode::SCRIPT_ERROR:
        return "Script execution failed";
    case ErrorCode::JOB_CANCELLED:
        return "Cancelled";
    case ErrorCode::JOB_STALE:
        return "Job exceeded the stuck-job timeout";
    default:
        return "An unexpected error occurred";
    }
}

int ErrorResponse::httpStatus(ErrorCode code)
{
    switch (code) {
    case ErrorCode::AUTH_MISSING_TOKEN:
    case ErrorCode::AUTH_INVALID_TOKEN:
        return 401;
    case ErrorCode::IP_NOT_WHITELISTED:
        return 403;
    case ErrorCode::SCRIPT_NOT_FOUND:
    case ErrorCode::REQUEST_NOT_FOUND:
    case ErrorCode::ROUTE_NOT_FOUND:
    case ErrorCode::ARTIFACT_NOT_FOUND:
        return 404;
    case ErrorCode::ARTIFACT_UNAVAILABLE:
        return 410;
    case ErrorCode::IDEMPOTENCY_KEY_IN_FLIGHT:
        return 409;
    case ErrorCode::IDEMPOTENCY_KEY_REUSED:
    case ErrorCode::THUMBNAIL_UNSUPPORTED:
        return 422;
    case ErrorCode::BODY_TOO_LARGE:
        return 413;
    case ErrorCode::RATE_LIMIT_EXCEEDED:
    case ErrorCode::CONCURRENT_LIMIT_EXCEEDED:
        return 429;
    case ErrorCode::BAD_REQUEST:
    case ErrorCode::INVALID_JSON:
    case ErrorCode::MISSING_FIELD:
    case ErrorCode::INVALID_FIELD:
    case ErrorCode::SCRIPT_TOO_LARGE:
    case ErrorCode::SCRIPT_FILE_NOT_FOUND:
    case ErrorCode::SCRIPT_FILE_NOT_FILE:
    case ErrorCode::SCRIPT_FILE_NOT_ABSOLUTE:
    case ErrorCode::SCRIPT_FILE_LOAD_FAILED:
    case ErrorCode::NOT_A_RENDER_REQUEST:
    case ErrorCode::REQUEST_ALREADY_FINISHED:
        return 400;
    case ErrorCode::SERVER_UNAVAILABLE:
    case ErrorCode::STUDIO_BUSY:
        return 503;
    case ErrorCode::INTERNAL_ERROR:
        return 500;
    case ErrorCode::SCRIPT_ERROR:
    case ErrorCode::JOB_CANCELLED:
    case ErrorCode::JOB_STALE:
        return 200;
    default:
        return 500;
    }
}

bool ErrorResponse::retryable(ErrorCode code)
{
    switch (code) {
    case ErrorCode::RATE_LIMIT_EXCEEDED:
    case ErrorCode::CONCURRENT_LIMIT_EXCEEDED:
    case ErrorCode::SERVER_UNAVAILABLE:
    case ErrorCode::STUDIO_BUSY:
    case ErrorCode::IDEMPOTENCY_KEY_IN_FLIGHT:
        return true;
    default:
        return false;
    }
}

std::string ErrorResponse::jsonEscape(const std::string& s)
{
    std::string out;
    out.reserve(s.size() + 8);
    for (size_t i = 0; i < s.size(); ++i) {
        unsigned char c = static_cast<unsigned char>(s[i]);
        switch (c) {
        case '"':  out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n";  break;
        case '\r': out += "\\r";  break;
        case '\t': out += "\\t";  break;
        default:
            if (c < 0x20) {
                char buf[8];
                snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned>(c));
                out += buf;
            } else {
                out += static_cast<char>(c);
            }
        }
    }
    return out;
}

std::string ErrorResponse::fields(ErrorCode code, const std::string& message)
{
    std::string json;
    json.reserve(128);
    json += "\"error_code\":\"";
    json += codeString(code);
    json += "\",\"error\":\"";
    json += jsonEscape(message.empty() ? std::string(defaultMessage(code)) : message);
    json += "\",\"retryable\":";
    json += retryable(code) ? "true" : "false";
    return json;
}

std::string ErrorResponse::build(ErrorCode code, const std::string& detail)
{
    std::string json;
    json.reserve(160);
    json += "{\"success\":false,";
    json += fields(code);
    if (!detail.empty()) {
        json += ",\"detail\":\"";
        json += jsonEscape(detail);
        json += "\"";
    }
    json += "}";
    return json;
}
