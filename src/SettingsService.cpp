#include "SettingsService.h"
#include <QtCore/qsettings.h>
#include <QtCore/qfile.h>
#include <QtCore/qdir.h>

const char* SettingsService::ORG = "DAZ 3D";
const char* SettingsService::APP = "DazScriptServer";


// ─── Public API ───────────────────────────────────────────────────────────────

ServerSettings SettingsService::load(QStringList& outMessages)
{
    QSettings qs(ORG, APP);
    runMigrations(qs);

    ServerSettings s = readFrom(qs);
    SettingsValidationResult vr = validate(s);

    for (const QString& err : vr.errors)
        outMessages << QString("[WARN] Settings: %1 — using default").arg(err);
    for (const QString& w : vr.warnings)
        outMessages << QString("[INFO] Settings: %1").arg(w);

    if (!vr.valid)
        s = clampToValid(s);

    return s;
}

bool SettingsService::save(const ServerSettings& s)
{
    ServerSettings clamped = clampToValid(s);
    QSettings qs(ORG, APP);
    writeTo(qs, clamped);
    qs.sync();
    return validate(s).valid;
}

namespace {
void checkRange(SettingsValidationResult& vr, const char* name, int value,
                ServerConfig::IntRange range)
{
    if (!range.contains(value))
        vr.addError(QString("%1 %2 out of range [%3, %4]")
                        .arg(name).arg(value).arg(range.min).arg(range.max));
}

// Out-of-range values fall back to the default (not the nearest bound).
void clampRange(int& value, ServerConfig::IntRange range, int fallback)
{
    if (!range.contains(value)) value = fallback;
}
}  // namespace

SettingsValidationResult SettingsService::validate(const ServerSettings& s) const
{
    SettingsValidationResult vr;

    if (s.host.trimmed().isEmpty())
        vr.addError("host must not be empty");

    // Ranges are shared with the settings pane spin boxes (ServerConfig.h).
    checkRange(vr, "port",                  s.port,                  ServerConfig::PORT_RANGE);
    checkRange(vr, "timeout",               s.timeoutSec,            ServerConfig::TIMEOUT_SEC_RANGE);
    checkRange(vr, "maxConcurrentRequests", s.maxConcurrentRequests, ServerConfig::MAX_CONCURRENT_REQUESTS_RANGE);
    checkRange(vr, "maxBodySizeMB",         s.maxBodySizeMB,         ServerConfig::MAX_BODY_SIZE_MB_RANGE);
    checkRange(vr, "maxScriptLengthKB",     s.maxScriptLengthKB,     ServerConfig::MAX_SCRIPT_LENGTH_KB_RANGE);
    checkRange(vr, "staleJobTimeoutMin",    s.staleJobTimeoutMin,    ServerConfig::ASYNC_STALE_RUNNING_TIMEOUT_RANGE_MIN);
    checkRange(vr, "rateLimitMax",          s.rateLimitMax,          ServerConfig::RATE_LIMIT_MAX_RANGE);
    checkRange(vr, "rateLimitWindow",       s.rateLimitWindow,       ServerConfig::RATE_LIMIT_WINDOW_RANGE);

    if (s.ipWhitelistEnabled && s.ipWhitelist.trimmed().isEmpty())
        vr.addWarning("IP whitelist is enabled but the whitelist is empty — all IPs will be blocked");

    return vr;
}

ServerSettings SettingsService::defaults()
{
    return ServerSettings{};
}

bool SettingsService::exportToFile(const QString& path,
                                   const ServerSettings& s,
                                   QStringList& outErrors) const
{
    QString tmpPath = path + ".tmp";
    {
        QSettings tmp(tmpPath, QSettings::IniFormat);
        tmp.setValue("version", CURRENT_VERSION);
        writeTo(tmp, s);
        tmp.sync();
        if (tmp.status() != QSettings::NoError) {
            outErrors << QString("Failed to write settings to %1").arg(tmpPath);
            return false;
        }
    }

    // Atomic rename: remove old file first (QFile::rename fails if dest exists on Windows)
    if (QFile::exists(path) && !QFile::remove(path)) {
        outErrors << QString("Could not replace existing file at %1").arg(path);
        QFile::remove(tmpPath);
        return false;
    }

    if (!QFile::rename(tmpPath, path)) {
        outErrors << QString("Could not rename temp file to %1").arg(path);
        QFile::remove(tmpPath);
        return false;
    }

    return true;
}

bool SettingsService::importFromFile(const QString& path,
                                     ServerSettings& outSettings,
                                     QStringList& outMessages)
{
    if (!QFile::exists(path)) {
        outMessages << QString("Import file not found: %1").arg(path);
        return false;
    }

    QSettings qs(path, QSettings::IniFormat);
    if (qs.status() != QSettings::NoError) {
        outMessages << QString("Could not open settings file: %1").arg(path);
        return false;
    }

    ServerSettings s = readFrom(qs);
    SettingsValidationResult vr = validate(s);

    for (const QString& err : vr.errors)
        outMessages << QString("[WARN] Imported settings: %1 — using default").arg(err);
    for (const QString& w : vr.warnings)
        outMessages << QString("[INFO] Imported settings: %1").arg(w);

    outSettings = vr.valid ? s : clampToValid(s);
    return true;
}

// ─── Private helpers ──────────────────────────────────────────────────────────

void SettingsService::runMigrations(QSettings& qs) const
{
    int storedVersion = qs.value("version", 0).toInt();
    if (storedVersion >= CURRENT_VERSION)
        return;

    // v0 → v1: first versioned schema. The key set is unchanged from the
    // unversioned legacy format; just stamp the version so future migrations
    // can detect the starting point.
    if (storedVersion < 1) {
        // No data transformations needed — existing keys are already in v1 format.
    }

    qs.setValue("version", CURRENT_VERSION);
    qs.sync();
}

ServerSettings SettingsService::readFrom(QSettings& qs) const
{
    const ServerSettings def;

    ServerSettings s;
    s.host                  = qs.value("host",                  def.host).toString();
    s.port                  = qs.value("port",                  def.port).toInt();
    s.timeoutSec            = qs.value("timeout",               def.timeoutSec).toInt();
    s.autoStart             = qs.value("autoStart",             def.autoStart).toBool();
    s.maxConcurrentRequests = qs.value("maxConcurrentRequests", def.maxConcurrentRequests).toInt();
    s.maxBodySizeMB         = qs.value("maxBodySizeMB",         def.maxBodySizeMB).toInt();
    s.maxScriptLengthKB     = qs.value("maxScriptLengthKB",     def.maxScriptLengthKB).toInt();
    s.staleJobTimeoutMin    = qs.value("staleJobTimeoutMin",    def.staleJobTimeoutMin).toInt();
    s.authEnabled           = qs.value("authEnabled",           def.authEnabled).toBool();
    s.ipWhitelistEnabled    = qs.value("ipWhitelistEnabled",    def.ipWhitelistEnabled).toBool();
    s.ipWhitelist           = qs.value("ipWhitelist",           def.ipWhitelist).toString();
    s.artifactRootsEnabled  = qs.value("artifactRootsEnabled",  def.artifactRootsEnabled).toBool();
    s.artifactRoots         = qs.value("artifactRoots",         def.artifactRoots).toString();
    s.rateLimitEnabled      = qs.value("rateLimitEnabled",      def.rateLimitEnabled).toBool();
    s.rateLimitMax          = qs.value("rateLimitMax",          def.rateLimitMax).toInt();
    s.rateLimitWindow       = qs.value("rateLimitWindow",       def.rateLimitWindow).toInt();
    return s;
}

void SettingsService::writeTo(QSettings& qs, const ServerSettings& s) const
{
    qs.setValue("host",                  s.host);
    qs.setValue("port",                  s.port);
    qs.setValue("timeout",               s.timeoutSec);
    qs.setValue("autoStart",             s.autoStart);
    qs.setValue("maxConcurrentRequests", s.maxConcurrentRequests);
    qs.setValue("maxBodySizeMB",         s.maxBodySizeMB);
    qs.setValue("maxScriptLengthKB",     s.maxScriptLengthKB);
    qs.setValue("staleJobTimeoutMin",    s.staleJobTimeoutMin);
    qs.setValue("authEnabled",           s.authEnabled);
    qs.setValue("ipWhitelistEnabled",    s.ipWhitelistEnabled);
    qs.setValue("ipWhitelist",           s.ipWhitelist);
    qs.setValue("artifactRootsEnabled",  s.artifactRootsEnabled);
    qs.setValue("artifactRoots",         s.artifactRoots);
    qs.setValue("rateLimitEnabled",      s.rateLimitEnabled);
    qs.setValue("rateLimitMax",          s.rateLimitMax);
    qs.setValue("rateLimitWindow",       s.rateLimitWindow);
}

ServerSettings SettingsService::clampToValid(const ServerSettings& s) const
{
    const ServerSettings def;
    ServerSettings out = s;

    if (out.host.trimmed().isEmpty())           out.host                  = def.host;
    clampRange(out.port,                  ServerConfig::PORT_RANGE,                    def.port);
    clampRange(out.timeoutSec,            ServerConfig::TIMEOUT_SEC_RANGE,             def.timeoutSec);
    clampRange(out.maxConcurrentRequests, ServerConfig::MAX_CONCURRENT_REQUESTS_RANGE, def.maxConcurrentRequests);
    clampRange(out.maxBodySizeMB,         ServerConfig::MAX_BODY_SIZE_MB_RANGE,        def.maxBodySizeMB);
    clampRange(out.maxScriptLengthKB,     ServerConfig::MAX_SCRIPT_LENGTH_KB_RANGE,    def.maxScriptLengthKB);
    clampRange(out.staleJobTimeoutMin,    ServerConfig::ASYNC_STALE_RUNNING_TIMEOUT_RANGE_MIN, def.staleJobTimeoutMin);
    clampRange(out.rateLimitMax,          ServerConfig::RATE_LIMIT_MAX_RANGE,          def.rateLimitMax);
    clampRange(out.rateLimitWindow,       ServerConfig::RATE_LIMIT_WINDOW_RANGE,       def.rateLimitWindow);

    return out;
}
