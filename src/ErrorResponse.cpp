#include "ErrorResponse.h"
#include <cstdio>

const char* ErrorResponse::codeString(ErrorCode code)
{
    switch (code) {
    case ErrorCode::AUTH_MISSING_TOKEN:        return "AUTH_MISSING_TOKEN";
    case ErrorCode::AUTH_INVALID_TOKEN:        return "AUTH_INVALID_TOKEN";
    case ErrorCode::IP_NOT_WHITELISTED:        return "IP_NOT_WHITELISTED";
    case ErrorCode::SCRIPT_NOT_FOUND:          return "SCRIPT_NOT_FOUND";
    case ErrorCode::BODY_TOO_LARGE:            return "BODY_TOO_LARGE";
    case ErrorCode::RATE_LIMIT_EXCEEDED:       return "RATE_LIMIT_EXCEEDED";
    case ErrorCode::CONCURRENT_LIMIT_EXCEEDED: return "CONCURRENT_LIMIT_EXCEEDED";
    case ErrorCode::INVALID_JSON:              return "INVALID_JSON";
    case ErrorCode::MISSING_FIELD:             return "MISSING_FIELD";
    case ErrorCode::INVALID_FIELD:             return "INVALID_FIELD";
    case ErrorCode::SCRIPT_TOO_LARGE:          return "SCRIPT_TOO_LARGE";
    case ErrorCode::SCRIPT_FILE_NOT_FOUND:     return "SCRIPT_FILE_NOT_FOUND";
    case ErrorCode::SCRIPT_FILE_NOT_FILE:      return "SCRIPT_FILE_NOT_FILE";
    case ErrorCode::SCRIPT_FILE_NOT_ABSOLUTE:  return "SCRIPT_FILE_NOT_ABSOLUTE";
    case ErrorCode::SCRIPT_FILE_LOAD_FAILED:   return "SCRIPT_FILE_LOAD_FAILED";
    case ErrorCode::SERVER_UNAVAILABLE:        return "SERVER_UNAVAILABLE";
    case ErrorCode::STUDIO_BUSY:               return "STUDIO_BUSY";
    case ErrorCode::INTERNAL_ERROR:            return "INTERNAL_ERROR";
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
    case ErrorCode::BODY_TOO_LARGE:
        return "Request body exceeds maximum allowed size";
    case ErrorCode::RATE_LIMIT_EXCEEDED:
        return "Rate limit exceeded: too many requests from this IP address, please wait before retrying";
    case ErrorCode::CONCURRENT_LIMIT_EXCEEDED:
        return "Server busy: maximum concurrent requests reached, please retry";
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
    case ErrorCode::SERVER_UNAVAILABLE:
        return "Service temporarily unavailable";
    case ErrorCode::STUDIO_BUSY:
        return "DAZ Studio's main thread is busy; please retry shortly";
    case ErrorCode::INTERNAL_ERROR:
        return "An internal server error occurred";
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
        return 404;
    case ErrorCode::BODY_TOO_LARGE:
        return 413;
    case ErrorCode::RATE_LIMIT_EXCEEDED:
    case ErrorCode::CONCURRENT_LIMIT_EXCEEDED:
        return 429;
    case ErrorCode::INVALID_JSON:
    case ErrorCode::MISSING_FIELD:
    case ErrorCode::INVALID_FIELD:
    case ErrorCode::SCRIPT_TOO_LARGE:
    case ErrorCode::SCRIPT_FILE_NOT_FOUND:
    case ErrorCode::SCRIPT_FILE_NOT_FILE:
    case ErrorCode::SCRIPT_FILE_NOT_ABSOLUTE:
    case ErrorCode::SCRIPT_FILE_LOAD_FAILED:
        return 400;
    case ErrorCode::SERVER_UNAVAILABLE:
    case ErrorCode::STUDIO_BUSY:
        return 503;
    case ErrorCode::INTERNAL_ERROR:
        return 500;
    default:
        return 500;
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

std::string ErrorResponse::build(ErrorCode code, const std::string& detail)
{
    std::string json;
    json.reserve(128);
    json += "{\"success\":false,\"error_code\":\"";
    json += codeString(code);
    json += "\",\"error\":\"";
    json += jsonEscape(defaultMessage(code));
    json += "\"";
    if (!detail.empty()) {
        json += ",\"detail\":\"";
        json += jsonEscape(detail);
        json += "\"";
    }
    json += "}";
    return json;
}
