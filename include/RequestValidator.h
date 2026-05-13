#pragma once
#include "ErrorResponse.h"
#include <string>
#include <QtCore/qstring.h>

// Result returned by all RequestValidator methods.
struct ValidationResult {
    bool        valid;
    ErrorCode   errorCode;
    std::string detail;

    static ValidationResult ok() {
        ValidationResult r;
        r.valid     = true;
        r.errorCode = ErrorCode::INVALID_JSON; // unused when valid
        return r;
    }
    static ValidationResult fail(ErrorCode code, const std::string& d = "") {
        ValidationResult r;
        r.valid     = false;
        r.errorCode = code;
        r.detail    = d;
        return r;
    }

    std::string toErrorJson() const { return ErrorResponse::build(errorCode, detail); }
    int         httpStatus()  const { return ErrorResponse::httpStatus(errorCode); }
};

// Centralizes all request validation rules for the server.
// Safe to call from both main thread and HTTP threads (no Qt event-loop dependencies).
class RequestValidator {
public:
    // Validate execute request: presence of script/scriptFile, script length, and
    // scriptFile path validity (absolute, exists, is a regular file).
    static ValidationResult validateExecuteFields(
        const QString& scriptFile,
        const QString& scriptText,
        int            maxScriptLengthKB);

    // Validate registry script name: 1-64 alphanumeric / hyphen / underscore chars.
    static ValidationResult validateScriptName(const QString& name);

    // Validate that a required string field is present (non-empty after trim).
    static ValidationResult validateRequiredField(
        const QString&     value,
        const std::string& fieldName);
};
