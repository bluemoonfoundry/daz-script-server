#pragma once

#include <QObject>
#include <QProcess>

// First-run JIT bootstrap of the shared Python toolchain the Package Runner
// (daz-script-server-5sw) needs before any package can be run:
//   1. Install uv into PackagePaths::baseDir()/bin if not already present
//      there: download one pinned uv release archive (kUvVersion in the
//      .cpp), check its SHA-256 against the digest compiled in here, and
//      only then extract the uv binary from it. Nothing downloaded is run
//      before that check -- no `curl | sh` / `irm | iex` installer script
//      (daz-script-server-yau7.4.6).
//   2. `uv python install 3.11`
//
// Bumping uv: change kUvVersion and every asset's sha256 together, copied
// from the release's <asset>.sha256 files (cross-check `gh release view
// <ver> -R astral-sh/uv --json assets`).
//
// That's it -- unlike daz-python-bridge's UvBootstrapper (which this is
// adapted from), there is no shared venv to create or install dependencies
// into here. Each package gets its own venv, created lazily by
// PackageDependencyInstaller on first run, not by this class. This class's
// only job is making sure `uv` and a Python 3.11 build exist at all, once,
// shared by every package's venv creation.
//
// Every step runs a QProcess asynchronously (never blocks the caller's
// thread); steps are chained off QProcess::finished so this is safe to drive
// from the Qt main thread. Call ensureReady() once; it no-ops the steps that
// are already satisfied (uv already present).
class PythonToolchainBootstrapper : public QObject {
	Q_OBJECT
public:
	explicit PythonToolchainBootstrapper(QObject *parent = nullptr);

	// Idempotent -- safe to call repeatedly; steps already satisfied are
	// skipped (uv already installed; `uv python install 3.11` itself is
	// already a fast no-op when 3.11 is already present).
	void ensureReady();

signals:
	// Emitted once uv is installed and Python 3.11 is available. Package
	// venvs can now be created.
	void ready();

	// step is a short machine-readable stage name ("install-uv",
	// "install-python") for status reporting. A checksum mismatch on the
	// downloaded uv archive fails "install-uv".
	void stepFailed(const QString &step, const QString &errorMessage);
	void stepStarted(const QString &step);
	void stepSucceeded(const QString &step);

private slots:
	void onDownloadUvFinished(int exitCode, QProcess::ExitStatus status);
	// macOS only (tar); declared unconditionally since moc doesn't see
	// Q_OS_* reliably.
	void onExtractUvFinished(int exitCode, QProcess::ExitStatus status);
	void onInstallPythonFinished(int exitCode, QProcess::ExitStatus status);

private:
	void installUv();
	void extractUv();
	void finishInstallUv(const QString &extractedBinary);
	void cleanUpUvDownload();
	void installPython();
	void fail(const QString &step, const QString &message);
	void fail(const QString &step, QProcess *process);

	QProcess *m_process = nullptr;
	QString m_uvArchivePath;  // downloaded release archive (deleted after install)
	QString m_uvStagingDir;   // extraction scratch dir (deleted after install)
};
