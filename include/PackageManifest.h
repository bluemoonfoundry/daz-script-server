#pragma once
// Validation of the untrusted fields a .dzpkg manifest.json hands to other
// processes (daz-script-server-yau7.4.5). Both run on the staged package,
// before ZipInstaller::commit(), so a rejected package never replaces an
// existing install.

#include <QString>
#include <QStringList>
#include <QVariant>

namespace PackageManifest {

// True when `dependency` is a plain PEP 508 requirement: a project name,
// optional [extras], optional comma-separated version specifiers. Anything
// else is rejected, in particular strings starting with '-' (uv would parse
// them as options, e.g. --index-url <attacker index>), direct URL references
// ("name @ https://..."), local paths and environment markers.
bool isValidDependency(const QString &dependency);

// Reads manifest["dependencies"]: absent means no dependencies; otherwise it
// must be a list of strings that all pass isValidDependency().
bool readDependencies(const QVariant &value, QStringList &dependencies, QString &errorMessage);

// entryPoint must be a relative path to a file inside packageDir: no
// absolute or drive-qualified path, no ".." segment, and its canonical path
// (symlinks resolved) must stay under packageDir's canonical path.
bool validateEntryPoint(const QString &packageDir, const QString &entryPoint, QString &errorMessage);

} // namespace PackageManifest
