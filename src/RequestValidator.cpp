#include "RequestValidator.h"
#include "JsonStd.h"
#include <QtCore/qfileinfo.h>
#include <QtCore/qregexp.h>

ValidationResult RequestValidator::validateExecuteFields(
    const QString& scriptFile,
    const QString& scriptText,
    int            maxScriptLengthKB)
{
    if (scriptFile.isEmpty() && scriptText.isEmpty())
        return ValidationResult::fail(ErrorCode::MISSING_FIELD,
            "Request must include either 'script' (inline code) or 'scriptFile' (absolute path)");

    if (!scriptText.isEmpty()) {
        int maxBytes = maxScriptLengthKB * 1024;
        if (scriptText.length() > maxBytes) {
            std::string detail =
                "Script is "    + std::to_string(scriptText.length()) +
                " bytes; maximum is " + std::to_string(maxScriptLengthKB) +
                " KB (" + std::to_string(maxBytes) + " bytes)";
            return ValidationResult::fail(ErrorCode::SCRIPT_TOO_LARGE, detail);
        }
    }

    if (!scriptFile.isEmpty()) {
        QFileInfo info(scriptFile);
        if (!info.isAbsolute())
            return ValidationResult::fail(ErrorCode::SCRIPT_FILE_NOT_ABSOLUTE);
        if (!info.exists())
            return ValidationResult::fail(ErrorCode::SCRIPT_FILE_NOT_FOUND,
                JsonStd::qstrToStd(scriptFile));
        if (!info.isFile())
            return ValidationResult::fail(ErrorCode::SCRIPT_FILE_NOT_FILE,
                JsonStd::qstrToStd(scriptFile));
    }

    return ValidationResult::ok();
}

ValidationResult RequestValidator::validateScriptName(const QString& name)
{
    if (name.isEmpty())
        return ValidationResult::fail(ErrorCode::MISSING_FIELD, "Field 'name' is required");

    QRegExp valid("^[A-Za-z0-9_-]{1,64}$");
    if (!valid.exactMatch(name))
        return ValidationResult::fail(ErrorCode::INVALID_FIELD,
            "Field 'name' must be 1-64 characters: letters, digits, hyphens, underscores only");

    return ValidationResult::ok();
}

ValidationResult RequestValidator::validateRequiredField(
    const QString&     value,
    const std::string& fieldName)
{
    if (value.trimmed().isEmpty())
        return ValidationResult::fail(ErrorCode::MISSING_FIELD,
            "Field '" + fieldName + "' is required");
    return ValidationResult::ok();
}
