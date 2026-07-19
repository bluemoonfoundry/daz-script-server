#pragma once

#include <QObject>
#include <QProcess>
#include <QStringList>

// Per-package venv creation and dependency resolution for the Package Runner
// (daz-script-server-5sw), adapted from daz-python-bridge's
// PluginDependencyInstaller.
//
// Run right after a .dzpkg is extracted/committed into place: creates an
// isolated venv at PackagePaths::packageVenvDir(packageId), bound to the
// Python 3.11 build PythonToolchainBootstrapper already ensured exists, then
// installs `dazpy` (always implicit -- every package's whole point is
// calling back into DAZ Studio via dazpy) plus whatever the manifest's
// "dependencies" array declares. Two packages pinning conflicting dependency
// versions cannot clobber each other because each gets its own venv rather
// than a shared site-packages.
//
// Unlike the daemon-oriented class this is adapted from, resolution is
// lazy and cached: run() first checks a marker file recording the exact
// dependency list last successfully resolved for this package, and skips
// straight to success if the manifest's current dependencies haven't
// changed and the venv still exists -- so opening the same package
// repeatedly doesn't re-run `uv pip install` every time, only when its
// declared dependencies actually change (e.g. a newer package version).
class PackageDependencyInstaller : public QObject {
	Q_OBJECT
public:
	explicit PackageDependencyInstaller(QObject *parent = nullptr);

	// Kicks off venv creation + dependency install for the package at
	// packageDir (already extracted, named packageId). `dependencies` is the
	// manifest's declared "dependencies" list -- `dazpy` is prepended
	// automatically, the caller should not include it. Emits finished()
	// exactly once when done (including the lazy-skip fast path); never
	// blocks the caller's thread.
	void run(const QString &packageId, const QString &packageDir, const QStringList &dependencies);

signals:
	// step is "create-venv" or "install-deps".
	void stepStarted(const QString &step);
	void stepSucceeded(const QString &step);
	void stepFailed(const QString &step, const QString &errorMessage);

	// Emitted exactly once, after the venv is confirmed ready (either freshly
	// resolved, or skipped because the cached marker already matched).
	void finished(const QString &packageId, bool success, const QString &errorMessage);

private slots:
	void onCreateVenvFinished(int exitCode, QProcess::ExitStatus status);
	void onInstallDepsFinished(int exitCode, QProcess::ExitStatus status);

private:
	void createVenv();
	void installDeps();
	void fail(const QString &step, const QString &message);
	void fail(const QString &step, QProcess *process);
	void succeed();
	QString venvPythonPath() const;
	QString statusFilePath() const;
	bool isAlreadyResolved() const;
	void writeStatusFile(bool success, const QString &step, const QString &errorMessage) const;

	QString    m_packageId;
	QString    m_packageDir;
	QStringList m_dependencies;
	QProcess  *m_process = nullptr;
};
