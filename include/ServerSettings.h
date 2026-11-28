#pragma once
#include <QtCore/qstring.h>
#include <QtCore/qstringlist.h>
#include "ServerConfig.h"

// All user-configurable server settings in one place.
struct ServerSettings {
    QString host                  = "127.0.0.1";
    int     port                  = ServerConfig::DEFAULT_PORT;
    int     queueTimeoutSec       = ServerConfig::DEFAULT_QUEUE_TIMEOUT_SEC;  // main-thread wait for sync requests
    bool    autoStart             = false;

    int     maxConcurrentRequests = ServerConfig::DEFAULT_MAX_CONCURRENT_REQUESTS;
    int     maxBodySizeMB         = ServerConfig::DEFAULT_MAX_BODY_SIZE_MB;
    int     maxScriptLengthKB     = ServerConfig::DEFAULT_MAX_SCRIPT_LENGTH_KB;
    int     staleJobTimeoutMin    = ServerConfig::ASYNC_STALE_RUNNING_TIMEOUT_MIN;  // async job running longer than this → "stale"

    bool    authEnabled           = true;

    bool    ipWhitelistEnabled    = false;
    QString ipWhitelist           = "127.0.0.1";

    // GET /artifacts serves only files inside these folders (';'-separated;
    // empty = ArtifactRoots::defaultRoots()). ~/.daz3d is always refused.
    bool    artifactRootsEnabled  = true;
    QString artifactRoots;

    bool    rateLimitEnabled      = false;
    int     rateLimitMax          = ServerConfig::DEFAULT_RATE_LIMIT_MAX;
    int     rateLimitWindow       = ServerConfig::DEFAULT_RATE_LIMIT_WINDOW;
};

struct SettingsValidationResult {
    bool        valid = true;
    QStringList errors;
    QStringList warnings;

    void addError(const QString& msg)   { errors   << msg; valid = false; }
    void addWarning(const QString& msg) { warnings << msg; }
};
