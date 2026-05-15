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

SettingsValidationResult SettingsService::validate(const ServerSettings& s) const
{
    SettingsValidationResult vr;

    if (s.host.trimmed().isEmpty())
        vr.addError("host must not be empty");

    if (s.port < 1024 || s.port > 65535)
        vr.addError(QString("port %1 out of range [1024, 65535]").arg(s.port));

    if (s.timeoutSec < 1 || s.timeoutSec > 300)
        vr.addError(QString("timeout %1 out of range [1, 300]").arg(s.timeoutSec));

    if (s.maxConcurrentRequests < 1 || s.maxConcurrentRequests > 50)
        vr.addError(QString("maxConcurrentRequests %1 out of range [1, 50]")
                        .arg(s.maxConcurrentRequests));

    if (s.maxBodySizeMB < 1 || s.maxBodySizeMB > 50)
        vr.addError(QString("maxBodySizeMB %1 out of range [1, 50]").arg(s.maxBodySizeMB));

    if (s.maxScriptLengthKB < 100 || s.maxScriptLengthKB > 10240)
        vr.addError(QString("maxScriptLengthKB %1 out of range [100, 10240]")
                        .arg(s.maxScriptLengthKB));

    if (s.rateLimitMax < 1 || s.rateLimitMax > 10000)
        vr.addError(QString("rateLimitMax %1 out of range [1, 10000]").arg(s.rateLimitMax));

    if (s.rateLimitWindow < 1 || s.rateLimitWindow > 3600)
        vr.addError(QString("rateLimitWindow %1 out of range [1, 3600]").arg(s.rateLimitWindow));

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
    s.authEnabled           = qs.value("authEnabled",           def.authEnabled).toBool();
    s.ipWhitelistEnabled    = qs.value("ipWhitelistEnabled",    def.ipWhitelistEnabled).toBool();
    s.ipWhitelist           = qs.value("ipWhitelist",           def.ipWhitelist).toString();
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
    qs.setValue("authEnabled",           s.authEnabled);
    qs.setValue("ipWhitelistEnabled",    s.ipWhitelistEnabled);
    qs.setValue("ipWhitelist",           s.ipWhitelist);
    qs.setValue("rateLimitEnabled",      s.rateLimitEnabled);
    qs.setValue("rateLimitMax",          s.rateLimitMax);
    qs.setValue("rateLimitWindow",       s.rateLimitWindow);
}

ServerSettings SettingsService::clampToValid(const ServerSettings& s) const
{
    const ServerSettings def;
    ServerSettings out = s;

    if (out.host.trimmed().isEmpty())           out.host                  = def.host;
    if (out.port < 1024 || out.port > 65535)    out.port                  = def.port;
    if (out.timeoutSec < 1 || out.timeoutSec > 300)
                                                out.timeoutSec            = def.timeoutSec;
    if (out.maxConcurrentRequests < 1 || out.maxConcurrentRequests > 50)
                                                out.maxConcurrentRequests = def.maxConcurrentRequests;
    if (out.maxBodySizeMB < 1 || out.maxBodySizeMB > 50)
                                                out.maxBodySizeMB         = def.maxBodySizeMB;
    if (out.maxScriptLengthKB < 100 || out.maxScriptLengthKB > 10240)
                                                out.maxScriptLengthKB     = def.maxScriptLengthKB;
    if (out.rateLimitMax < 1 || out.rateLimitMax > 10000)
                                                out.rateLimitMax          = def.rateLimitMax;
    if (out.rateLimitWindow < 1 || out.rateLimitWindow > 3600)
                                                out.rateLimitWindow       = def.rateLimitWindow;

    return out;
}
