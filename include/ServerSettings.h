#pragma once
#include <QtCore/qstring.h>
#include <QtCore/qstringlist.h>

// All user-configurable server settings in one place.
struct ServerSettings {
    QString host                  = "127.0.0.1";
    int     port                  = 18811;
    int     timeoutSec            = 30;
    bool    autoStart             = false;

    int     maxConcurrentRequests = 10;
    int     maxBodySizeMB         = 5;
    int     maxScriptLengthKB     = 1024;

    bool    authEnabled           = true;

    bool    ipWhitelistEnabled    = false;
    QString ipWhitelist           = "127.0.0.1";

    bool    rateLimitEnabled      = false;
    int     rateLimitMax          = 60;
    int     rateLimitWindow       = 60;
};

struct SettingsValidationResult {
    bool        valid = true;
    QStringList errors;
    QStringList warnings;

    void addError(const QString& msg)   { errors   << msg; valid = false; }
    void addWarning(const QString& msg) { warnings << msg; }
};
