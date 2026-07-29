#pragma once

#include <dzimporter.h>

#include <QString>
#include <QStringList>
#include <QVariant>

// Registers the .dzpkg extension with DzImportMgr so opening one (File >
// Open, drag-drop, content-library double-click) works exactly like opening
// a .dsa today -- no separate plugin-management pane involved (Package
// Runner epic, daz-script-server-5sw).
//
// read() flow:
//   1. ZipInstaller::extractToStaging() the .dzpkg into a staging dir.
//   2. Parse and validate manifest.json (schemaVersion/id/entryPoint required).
//   3. ZipInstaller::commit() into PackagePaths::packagesDir() (overwrite-by-id
//      -- opening a newer version of an already-opened package replaces it).
//   4. If manifest "interactive": show DzPackageInputsDialog; Cancel aborts
//      read() cleanly (DZ_USER_CANCELLED_OPERATION, not an error). Otherwise
//      inputs = {}.
//   5. PythonToolchainBootstrapper::ensureReady() (uv + Python 3.11 present).
//   6. PackageDependencyInstaller::run() -- lazy/cached per-package venv.
//   7. Spawn dsp_runner (written out from a Qt resource) against the venv's
//      python, by direct file path, synchronously, with a cancellable
//      progress dialog.
//   8. Parse the final stdout JSON envelope line; report result/error.
//
// Steps 5-7 are all QProcess-async under the hood; read() must return
// synchronously per the DzImporter contract, so each async step is driven to
// completion with a local QEventLoop rather than being made "actually"
// synchronous.
class DzPackageImporter : public DzImporter {
	Q_OBJECT
public:
	DzPackageImporter();
	virtual ~DzPackageImporter();

	virtual bool	recognize(const QString &filename) const;
	virtual int		getNumExtensions() const;
	virtual QString	getExtension(int i) const;
#if DAZ_SDK_MAJOR_VERSION >= 6
	virtual QString	getExtensionDescription(int i) const;
#endif
	virtual QString	getDescription() const;

public slots:
	// A .dzpkg has no per-import options to configure (its inputs come from
	// DzPackageInputsDialog, driven by the manifest, not from DzFileIOSettings) --
	// this override exists only because DzFileIO declares it pure virtual.
	virtual void	getDefaultOptions(DzFileIOSettings *options) const;

protected:
	virtual DzError	read(const QString &filename, const DzFileIOSettings *options);

private:
	// Returns "" (and leaves errorMessage empty) if the package is
	// non-interactive; a manifest with interactive == true but a rejected
	// dialog sets cancelled = true.
	QVariantMap collectInputs(const QVariantMap &manifest, bool &cancelled) const;

	// Blocks (via a local QEventLoop) until the toolchain is ready or a step
	// fails. Returns false and fills errorMessage on failure.
	bool ensureToolchainReady(QString &errorMessage) const;

	// Blocks until the package's venv is confirmed ready (freshly resolved or
	// cached). Returns false and fills errorMessage on failure.
	bool ensureDependencies(const QString &packageId, const QString &packageDir,
		const QStringList &dependencies, QString &errorMessage) const;

	// Writes the bundled dsp_runner.py resource out to
	// PackagePaths::baseDir()/dsp_runner.py (overwritten every call -- always
	// matches the DLL currently loaded) and returns that path, or ""
	// on failure.
	QString writeDspRunner(QString &errorMessage) const;

	// Runs dsp_runner synchronously against packageVenvPython, returns its
	// parsed final JSON envelope. success is false and errorMessage is filled
	// if the subprocess itself failed to run or produced no parseable
	// envelope (distinct from the envelope's own "success": false, which is
	// a normal package-reported failure, not a plumbing failure).
	QVariantMap runPackage(const QString &packageVenvPython, const QString &dspRunnerPath,
		const QString &entryPointPath, const QVariantMap &inputs,
		bool &success, QString &errorMessage) const;
};
