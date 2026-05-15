#pragma once
#include <QtCore/qstring.h>
#include <QtCore/qstringlist.h>
#include "ServerSettings.h"

class QSettings;

// Centralises all server-config persistence: load, save, validate, migrate,
// and file-based export/import. Metrics and token storage remain in their
// own service classes (MetricsCollector / AuthenticationService).
//
// Plain class (no Q_OBJECT) — consistent with the rest of the service layer
// in this project (see AsyncRequestManager.h for the rationale).
class SettingsService {
public:
    SettingsService() = default;

    // Load from platform QSettings. Runs migration if needed, validates each
    // field and replaces invalid values with defaults before returning.
    // Appends diagnostic messages to outMessages.
    ServerSettings           load(QStringList& outMessages);

    // Validate then persist to platform QSettings.
    // Returns false if validation found errors (settings are saved clamped to valid ranges).
    bool                     save(const ServerSettings& s);

    // Pure validation — no side effects.
    SettingsValidationResult validate(const ServerSettings& s) const;

    // Return a struct filled with compile-time defaults.
    static ServerSettings defaults();

    // Export settings to an INI file at path (atomic: write temp then rename).
    // Returns false and appends an error to outErrors on failure.
    bool exportToFile(const QString& path, const ServerSettings& s,
                      QStringList& outErrors) const;

    // Import settings from an INI file. Validates after loading; invalid fields
    // fall back to defaults. Returns false if the file could not be opened.
    bool importFromFile(const QString& path, ServerSettings& outSettings,
                        QStringList& outMessages);

private:
    // Increment when the QSettings schema changes to trigger migration logic.
    static const int CURRENT_VERSION = 1;

    static const char* ORG;
    static const char* APP;

    // Run all pending migrations in order. Writes the final version key.
    void runMigrations(QSettings& qs) const;

    // Read all keys from qs into a ServerSettings struct (no validation).
    ServerSettings readFrom(QSettings& qs) const;

    // Write all settings keys to qs (does not touch the version key).
    void writeTo(QSettings& qs, const ServerSettings& s) const;

    // Return a copy of s with each invalid field replaced by its default.
    ServerSettings clampToValid(const ServerSettings& s) const;
};
