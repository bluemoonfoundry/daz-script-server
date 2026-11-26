#include "DzPackageImporter.h"

#include "JsonStd.h"
#include "PackageDependencyInstaller.h"
#include "PackageManifest.h"
#include "PackagePaths.h"
#include "PortableFs.h"
#include "PythonToolchainBootstrapper.h"
#include "ZipInstaller.h"

#if DAZ_SDK_MAJOR_VERSION >= 6
#include <QtWidgets/qmessagebox.h>
#include <QtWidgets/qprogressdialog.h>
#else
#include <QtGui/qmessagebox.h>
#include <QtGui/qprogressdialog.h>
#endif

#include "DzPackageInputsDialog.h"

#include <dzapp.h>
#include <dzerrorcodes.h>

#include <QDir>
#include <QEventLoop>
#include <QFile>
#include <QProcess>
#include <QTemporaryFile>
#include <QTimer>

// Small QObject helpers to bridge PythonToolchainBootstrapper's and
// PackageDependencyInstaller's async QProcess-driven signals back into
// read()'s synchronous DzImporter contract via a local QEventLoop. Qt 4.8
// (SDK4 build) has no PMF/lambda connect() overload -- only the string-based
// SIGNAL()/SLOT() form -- so real slots are used here rather than lambdas,
// same as every other Qt4/Qt6-dual-build class in this plugin.
//
// Each waiter records that its signal arrived, and callers skip loop.exec()
// when it already has: QEventLoop::exec() clears the exit flag on entry, so a
// quit() delivered before exec() is lost and exec() never returns. That
// happens when the signal is emitted inside the starting call -- run() on an
// already-resolved package (re-import), or ensureReady() failing to create
// the base dir (daz-script-server-yau7.4.2).
class ToolchainWaiter : public QObject {
	Q_OBJECT
public:
	bool ok = false;
	bool done = false;
	QString errorMessage;
public slots:
	void onReady() { ok = true; done = true; }
	void onStepFailed(const QString &step, const QString &message) {
		errorMessage = QString::fromLatin1("%1: %2").arg(step).arg(message);
		done = true;
	}
};

class DependencyWaiter : public QObject {
	Q_OBJECT
public:
	bool ok = false;
	bool done = false;
	QString errorMessage;
public slots:
	void onFinished(const QString & /*packageId*/, bool success, const QString &message) {
		ok = success;
		errorMessage = message;
		done = true;
	}
};

// QProcess::waitForFinished() blocks the calling thread without running the
// Qt event loop -- fatal here, since this plugin's own HTTP listener (port
// 18811) runs on that same main-thread event loop, and every package's whole
// point is calling back into it via dazpy. A dsp_runner subprocess spawned
// from inside DAZ Studio would deadlock waiting for a response nothing is
// left running to send (confirmed empirically: running dsp_runner directly
// from a shell succeeded immediately, but the same package hung when run
// from within DzPackageImporter::read() until now). A local QEventLoop
// driven by QProcess::finished(), same pattern as ToolchainWaiter/
// DependencyWaiter above, keeps the event loop alive while waiting.
//
// A single-shot QTimer bounds that wait (daz-script-server-yau7.4.3): a hung
// package would otherwise block read() forever, and with it the HTTP API.
class ProcessWaiter : public QObject {
	Q_OBJECT
public:
	bool finished = false;
	bool timedOut = false;
public slots:
	void onFinished(int /*exitCode*/, QProcess::ExitStatus /*status*/) { finished = true; }
	void onTimeout() { timedOut = true; }
};

#include "DzPackageImporter.moc"

namespace {

const char *kManifestFileName = "manifest.json";

bool readManifest(const QString &stagingDir, QVariantMap &manifest, QString &errorMessage) {
	QFile file(QDir(stagingDir).filePath(kManifestFileName));
	if (!file.open(QIODevice::ReadOnly)) {
		errorMessage = QString::fromLatin1("Package is missing %1").arg(kManifestFileName);
		return false;
	}

	std::string parseError;
	if (!JsonStd::parseObject(file.readAll(), manifest, parseError)) {
		errorMessage = QString::fromLatin1("Invalid %1: %2")
			.arg(kManifestFileName).arg(QString::fromStdString(parseError));
		return false;
	}

	if (manifest.value("id").toString().isEmpty() ||
		manifest.value("entryPoint").toString().isEmpty()) {
		errorMessage = QString::fromLatin1("%1 must declare \"id\" and \"entryPoint\"").arg(kManifestFileName);
		return false;
	}

	// dependencies go to `uv pip install` and entryPoint to the runner
	// subprocess: reject option-like requirements and paths that leave the
	// package (yau7.4.5). Checked on the staged copy, before commit().
	QStringList dependencies;
	int timeoutSeconds = 0;
	if (!PackageManifest::readDependencies(manifest.value("dependencies"), dependencies, errorMessage) ||
		!PackageManifest::validateEntryPoint(stagingDir, manifest.value("entryPoint").toString(), errorMessage) ||
		!PackageManifest::readTimeoutSeconds(manifest.value("timeoutSeconds"), timeoutSeconds, errorMessage)) {
		return false;
	}

	return true;
}

} // namespace

DzPackageImporter::DzPackageImporter() : DzImporter() {}

DzPackageImporter::~DzPackageImporter() {}

bool DzPackageImporter::recognize(const QString &filename) const {
	return filename.endsWith(QString::fromLatin1(".dzpkg"), Qt::CaseInsensitive);
}

int DzPackageImporter::getNumExtensions() const {
	return 1;
}

QString DzPackageImporter::getExtension(int /*i*/) const {
	return QString::fromLatin1("dzpkg");
}

#if DAZ_SDK_MAJOR_VERSION >= 6
QString DzPackageImporter::getExtensionDescription(int /*i*/) const {
	return QString::fromLatin1("Daz Studio Python Package (*.dzpkg)");
}
#endif

QString DzPackageImporter::getDescription() const {
	return QString::fromLatin1("Python Package");
}

void DzPackageImporter::getDefaultOptions(DzFileIOSettings * /*options*/) const {
	// No per-import options -- see the header comment on this override.
}

bool DzPackageImporter::ensureToolchainReady(QString &errorMessage) const {
	PythonToolchainBootstrapper bootstrapper;
	ToolchainWaiter waiter;
	QEventLoop loop;

	connect(&bootstrapper, SIGNAL(ready()), &waiter, SLOT(onReady()));
	connect(&bootstrapper, SIGNAL(ready()), &loop, SLOT(quit()));
	connect(&bootstrapper, SIGNAL(stepFailed(QString, QString)), &waiter, SLOT(onStepFailed(QString, QString)));
	connect(&bootstrapper, SIGNAL(stepFailed(QString, QString)), &loop, SLOT(quit()));

	bootstrapper.ensureReady();
	if (!waiter.done) {
		loop.exec();
	}

	errorMessage = waiter.errorMessage;
	return waiter.ok;
}

bool DzPackageImporter::ensureDependencies(const QString &packageId, const QString &packageDir,
	const QStringList &dependencies, QString &errorMessage) const {
	PackageDependencyInstaller installer;
	DependencyWaiter waiter;
	QEventLoop loop;

	connect(&installer, SIGNAL(finished(QString, bool, QString)), &waiter, SLOT(onFinished(QString, bool, QString)));
	connect(&installer, SIGNAL(finished(QString, bool, QString)), &loop, SLOT(quit()));

	installer.run(packageId, packageDir, dependencies);
	if (!waiter.done) {
		loop.exec();
	}

	errorMessage = waiter.errorMessage;
	return waiter.ok;
}

QVariantMap DzPackageImporter::collectInputs(const QVariantMap &manifest, bool &cancelled) const {
	cancelled = false;
	if (!manifest.value("interactive").toBool()) {
		return QVariantMap();
	}

	DzPackageInputsDialog dialog(nullptr, manifest.value("displayName").toString(),
		manifest.value("inputs").toList());
	if (dialog.exec() != QDialog::Accepted) {
		cancelled = true;
		return QVariantMap();
	}

	return dialog.collectedInputs();
}

QString DzPackageImporter::writeDspRunner(QString &errorMessage) const {
	if (!PackagePaths::ensureBaseDirExists()) {
		errorMessage = QString::fromLatin1("Could not create %1").arg(PackagePaths::baseDir());
		return QString();
	}

	QFile resource(QString::fromLatin1(":/package_runner/dsp_runner.py"));
	if (!resource.open(QIODevice::ReadOnly)) {
		errorMessage = QString::fromLatin1("Missing bundled dsp_runner.py resource");
		return QString();
	}
	const QByteArray contents = resource.readAll();

	const QString outPath = QDir(PackagePaths::baseDir()).filePath("dsp_runner.py");
	QFile out(outPath);
	if (!out.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
		errorMessage = QString::fromLatin1("Could not write %1").arg(outPath);
		return QString();
	}
	const bool written = out.write(contents) == contents.size() && out.flush();
	out.close();
	if (!written || out.error() != QFile::NoError) {
		errorMessage = QString::fromLatin1("Could not write %1: %2").arg(outPath, out.errorString());
		return QString();
	}

	return outPath;
}

QVariantMap DzPackageImporter::runPackage(const QString &packageVenvPython, const QString &dspRunnerPath,
	const QString &entryPointPath, const QVariantMap &inputs, int timeoutSeconds,
	bool &success, QString &errorMessage) const {
	success = false;

	QTemporaryFile inputsFile(QDir::temp().filePath("dsp_inputs_XXXXXX.json"));
	inputsFile.setAutoRemove(true);
	if (!inputsFile.open()) {
		errorMessage = QString::fromLatin1("Could not create a temp file for package inputs");
		return QVariantMap();
	}
	const QByteArray inputsBytes = JsonStd::variantToJsonBytes(inputs);
	if (inputsFile.write(inputsBytes) != inputsBytes.size() || !inputsFile.flush()) {
		errorMessage = QString::fromLatin1("Could not write package inputs: %1").arg(inputsFile.errorString());
		return QVariantMap();
	}
	const QString inputsPath = inputsFile.fileName();

	QProcess process;
	ProcessWaiter waiter;
	QEventLoop loop;
	connect(&process, SIGNAL(finished(int, QProcess::ExitStatus)), &waiter, SLOT(onFinished(int, QProcess::ExitStatus)));
	connect(&process, SIGNAL(finished(int, QProcess::ExitStatus)), &loop, SLOT(quit()));
	QTimer timeout;
	timeout.setSingleShot(true);
	connect(&timeout, SIGNAL(timeout()), &waiter, SLOT(onTimeout()));
	connect(&timeout, SIGNAL(timeout()), &loop, SLOT(quit()));

	process.start(packageVenvPython, QStringList() << dspRunnerPath << entryPointPath << inputsPath);
	if (!process.waitForStarted(10000)) {
		errorMessage = QString::fromLatin1("Could not launch the package's Python interpreter");
		return QVariantMap();
	}
	timeout.start(timeoutSeconds * 1000);
	if (!waiter.finished) {
		loop.exec();
	}
	timeout.stop();
	if (waiter.timedOut && !waiter.finished) {
		// kill() is asynchronous; reap briefly so ~QProcess doesn't block
		// on a process that ignores the signal.
		process.kill();
		process.waitForFinished(5000);
		errorMessage = QString::fromLatin1("Package did not finish within %1 seconds and was stopped "
			"(raise \"timeoutSeconds\" in manifest.json if it needs longer)").arg(timeoutSeconds);
		return QVariantMap();
	}
	if (!waiter.finished) {
		errorMessage = QString::fromLatin1("Package process did not exit cleanly");
		return QVariantMap();
	}

	const QByteArray stdoutBytes = process.readAllStandardOutput();
	// dsp_runner prints exactly one JSON line as its last line of output;
	// take the last non-empty line rather than assuming stdout has nothing
	// else on it, since a misbehaving dependency could still write to the
	// real stdout despite dsp_runner's own redirect_stdout capture.
	QList<QByteArray> lines = stdoutBytes.split('\n');
	QByteArray lastLine;
	for (int i = lines.size() - 1; i >= 0; --i) {
		if (!lines.at(i).trimmed().isEmpty()) {
			lastLine = lines.at(i).trimmed();
			break;
		}
	}

	QVariantMap envelope;
	std::string parseError;
	if (lastLine.isEmpty() || !JsonStd::parseObject(lastLine, envelope, parseError)) {
		errorMessage = QString::fromLatin1("Package process produced no result: %1")
			.arg(QString::fromUtf8(process.readAllStandardError()));
		return QVariantMap();
	}

	success = true;
	return envelope;
}

DzError DzPackageImporter::read(const QString &filename, const DzFileIOSettings * /*options*/) {
	if (!PackagePaths::ensureBaseDirExists()) {
		QMessageBox::critical(nullptr, QString::fromLatin1("Package Error"),
			QString::fromLatin1("Could not create %1").arg(PackagePaths::baseDir()));
		return DZ_OPERATION_FAILED_ERROR;
	}

	ZipInstaller installer(PackagePaths::packagesDir());
	ZipInstaller::StageResult stage = installer.extractToStaging(filename);
	if (!stage.success) {
		QMessageBox::critical(nullptr, QString::fromLatin1("Package Error"), stage.errorMessage);
		return DZ_FILE_FORMAT_ERROR;
	}

	QVariantMap manifest;
	QString errorMessage;
	if (!readManifest(stage.stagingDir, manifest, errorMessage)) {
		PortableFs::removeRecursively(stage.stagingDir);
		QMessageBox::critical(nullptr, QString::fromLatin1("Package Error"), errorMessage);
		return DZ_FILE_FORMAT_ERROR;
	}

	// Ask for inputs before commit(): commit() replaces any existing install of
	// this package id, so a Cancel after it would leave the old version
	// overwritten by a package the user chose not to run. Cancelling here only
	// discards the staging dir.
	bool cancelled = false;
	QVariantMap inputs = collectInputs(manifest, cancelled);
	if (cancelled) {
		PortableFs::removeRecursively(stage.stagingDir);
		return DZ_USER_CANCELLED_OPERATION;
	}

	ZipInstaller::CommitResult commitResult = installer.commit(stage.packageId, stage.stagingDir);
	if (!commitResult.success) {
		PortableFs::removeRecursively(stage.stagingDir);
		QMessageBox::critical(nullptr, QString::fromLatin1("Package Error"), commitResult.errorMessage);
		return DZ_OPERATION_FAILED_ERROR;
	}

	QProgressDialog progress(QString::fromLatin1("Preparing %1...").arg(manifest.value("displayName").toString()),
		QString(), 0, 0, nullptr);
	progress.setCancelButton(nullptr);
	progress.setWindowModality(Qt::WindowModal);
	progress.show();

	if (!ensureToolchainReady(errorMessage)) {
		QMessageBox::critical(nullptr, QString::fromLatin1("Package Error"),
			QString::fromLatin1("Could not prepare the Python toolchain: %1").arg(errorMessage));
		return DZ_OPERATION_FAILED_ERROR;
	}

	QStringList dependencies;
	PackageManifest::readDependencies(manifest.value("dependencies"), dependencies, errorMessage); // validated in readManifest()
	if (!ensureDependencies(stage.packageId, commitResult.finalPackageDir, dependencies, errorMessage)) {
		QMessageBox::critical(nullptr, QString::fromLatin1("Package Error"),
			QString::fromLatin1("Could not prepare %1's Python environment: %2")
				.arg(manifest.value("displayName").toString()).arg(errorMessage));
		return DZ_OPERATION_FAILED_ERROR;
	}

	const QString dspRunnerPath = writeDspRunner(errorMessage);
	if (dspRunnerPath.isEmpty()) {
		QMessageBox::critical(nullptr, QString::fromLatin1("Package Error"), errorMessage);
		return DZ_OPERATION_FAILED_ERROR;
	}

	const QString entryPointPath = QDir(commitResult.finalPackageDir)
		.filePath(manifest.value("entryPoint").toString());
	const QString venvPython = PackagePaths::packageVenvPythonPath(stage.packageId);

	progress.close();

	int timeoutSeconds = PackageManifest::kDefaultTimeoutSeconds;
	PackageManifest::readTimeoutSeconds(manifest.value("timeoutSeconds"), timeoutSeconds, errorMessage); // validated in readManifest()

	bool ranOk = false;
	QVariantMap envelope = runPackage(venvPython, dspRunnerPath, entryPointPath, inputs, timeoutSeconds,
		ranOk, errorMessage);
	if (!ranOk) {
		QMessageBox::critical(nullptr, QString::fromLatin1("Package Error"), errorMessage);
		return DZ_OPERATION_FAILED_ERROR;
	}

	// A package's own print() debugging comes back as "output" -- surface it
	// in DAZ Studio's log regardless of success/failure, same as .dsa script
	// output would be.
	for (const QVariant &line : envelope.value("output").toList()) {
		dzApp->log(QString::fromLatin1("[%1] %2").arg(manifest.value("displayName").toString()).arg(line.toString()));
	}

	if (!envelope.value("success").toBool()) {
		QMessageBox::warning(nullptr, manifest.value("displayName").toString(),
			envelope.value("error").toString());
		return DZ_OPERATION_FAILED_ERROR;
	}

	dzApp->log(QString::fromLatin1("[%1] Result: %2")
		.arg(manifest.value("displayName").toString())
		.arg(QString::fromStdString(JsonStd::variantToJson(envelope.value("result")))));

	return DZ_NO_ERROR;
}

// Manually included -- CMAKE_AUTOMOC_MOC_OPTIONS -i (top-level CMakeLists.txt)
// is set project-wide, which suppresses moc's default self-include of this
// class's own header for every Q_OBJECT class, not just pluginmain.cpp's
// inline one it was added for. Same pattern PythonToolchainBootstrapper.cpp/
// PackageDependencyInstaller.cpp/DzPackageInputsDialog.cpp already use.
#include "moc_DzPackageImporter.cpp"
