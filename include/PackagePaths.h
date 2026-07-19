#pragma once

#include <QString>

// Resolves the on-disk layout the Package Runner (daz-script-server-5sw) and
// its per-package venvs live under:
//
//   <base>/bin/uv[.exe]                   the vendored uv binary
//   <base>/packages/<id>/                 extracted .dzpkg contents (manifest.json, entry point, assets)
//   <base>/packages/<id>/venv/            that package's own isolated venv, created
//                                          lazily on first run by PackageDependencyInstaller
//
// <base> is QStandardPaths::AppDataLocation + "/DazScriptServer", i.e.
// AppData/Daz 3D/Studio4/DazScriptServer on Windows, since the host DAZ
// Studio process has already set QCoreApplication's organization/application
// name. Unlike daz-python-bridge's DaemonPaths (which this is adapted from),
// there is no separate "run_venv" -- there's no persistent daemon process
// here at all, only per-package venvs.
class PackagePaths {
public:
	static QString baseDir();
	static QString uvBinaryPath();
	static QString packagesDir();
	static QString packageDir(const QString &packageId);
	static QString packageVenvDir(const QString &packageId);

	// Ensures baseDir() (and its bin/ subdirectory) exist on disk.
	// Returns false if creation failed.
	static bool ensureBaseDirExists();
};
