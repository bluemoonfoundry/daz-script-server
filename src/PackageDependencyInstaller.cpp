#include "PackageDependencyInstaller.h"

#include "JsonStd.h"
#include "PackagePaths.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>

PackageDependencyInstaller::PackageDependencyInstaller(QObject *parent) : QObject(parent) {}

QString PackageDependencyInstaller::venvPythonPath() const {
#ifdef Q_OS_WIN
	return QDir(PackagePaths::packageVenvDir(m_packageId)).filePath("Scripts/python.exe");
#else
	return QDir(PackagePaths::packageVenvDir(m_packageId)).filePath("bin/python");
#endif
}

QString PackageDependencyInstaller::statusFilePath() const {
	return QDir(m_packageDir).filePath(".venv_status.json");
}

bool PackageDependencyInstaller::isAlreadyResolved() const {
	if (!QFileInfo(venvPythonPath()).exists()) {
		return false;
	}

	QFile statusFile(statusFilePath());
	if (!statusFile.open(QIODevice::ReadOnly)) {
		return false;
	}
	QVariantMap status;
	std::string parseError;
	if (!JsonStd::parseObject(statusFile.readAll(), status, parseError)) {
		return false;
	}
	if (status.value(QString::fromLatin1("state")).toString() != QString::fromLatin1("ok")) {
		return false;
	}

	QStringList cachedDeps;
	for (const QVariant &dep : status.value(QString::fromLatin1("dependencies")).toList()) {
		cachedDeps << dep.toString();
	}
	QStringList currentDeps = m_dependencies;
	currentDeps.sort();
	cachedDeps.sort();
	return currentDeps == cachedDeps;
}

void PackageDependencyInstaller::writeStatusFile(bool success, const QString &step, const QString &errorMessage) const {
	QVariantMap status;
	status["state"] = success ? QString::fromLatin1("ok") : QString::fromLatin1("failed");
	if (!success) {
		status["step"] = step;
		status["error"] = errorMessage;
	}
	QVariantList depsList;
	for (const QString &dep : m_dependencies) {
		depsList << dep;
	}
	status["dependencies"] = depsList;

	QFile statusFile(statusFilePath());
	if (statusFile.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
		statusFile.write(JsonStd::variantToJsonBytes(status));
	}
}

void PackageDependencyInstaller::fail(const QString &step, const QString &message) {
	emit stepFailed(step, message);
	writeStatusFile(false, step, message);
	emit finished(m_packageId, false, message);
}

void PackageDependencyInstaller::fail(const QString &step, QProcess *process) {
	const QString message = QString::fromUtf8(process->readAllStandardError());
	fail(step, message.isEmpty() ? process->errorString() : message);
}

void PackageDependencyInstaller::succeed() {
	writeStatusFile(true, QString(), QString());
	emit finished(m_packageId, true, QString());
}

void PackageDependencyInstaller::run(const QString &packageId, const QString &packageDir, const QStringList &dependencies) {
	m_packageId = packageId;
	m_packageDir = packageDir;
	m_dependencies = dependencies;

	if (isAlreadyResolved()) {
		emit finished(m_packageId, true, QString());
		return;
	}
	createVenv();
}

// ─── Step 1: create the package's own isolated venv ─────────────────────────

void PackageDependencyInstaller::createVenv() {
	emit stepStarted("create-venv");

	m_process = new QProcess(this);
	// --clear: re-running this over an existing venv (e.g. a package's
	// dependency list changed between versions) must not leave stale
	// packages behind from a previous resolution.
	const QStringList arguments = QStringList()
		<< "venv" << PackagePaths::packageVenvDir(m_packageId) << "--python" << "3.11" << "--clear";

	connect(m_process, SIGNAL(finished(int, QProcess::ExitStatus)),
	        this, SLOT(onCreateVenvFinished(int, QProcess::ExitStatus)));
	m_process->start(PackagePaths::uvBinaryPath(), arguments);
}

void PackageDependencyInstaller::onCreateVenvFinished(int exitCode, QProcess::ExitStatus status) {
	if (status != QProcess::NormalExit || exitCode != 0) {
		fail("create-venv", m_process);
		return;
	}
	emit stepSucceeded("create-venv");
	installDeps();
}

// ─── Step 2: install dazpy + the manifest's declared dependencies ───────────
// dazpy is always implicit -- every package's whole point is calling back
// into DAZ Studio via dazpy, so the manifest never needs to (and shouldn't)
// declare it itself.

void PackageDependencyInstaller::installDeps() {
	emit stepStarted("install-deps");

	m_process = new QProcess(this);
	QStringList arguments = QStringList()
		<< "pip" << "install" << "--python" << venvPythonPath()
		<< "dazpy";
	arguments += m_dependencies;

	connect(m_process, SIGNAL(finished(int, QProcess::ExitStatus)),
	        this, SLOT(onInstallDepsFinished(int, QProcess::ExitStatus)));
	m_process->start(PackagePaths::uvBinaryPath(), arguments);
}

void PackageDependencyInstaller::onInstallDepsFinished(int exitCode, QProcess::ExitStatus status) {
	if (status != QProcess::NormalExit || exitCode != 0) {
		fail("install-deps", m_process);
		return;
	}
	emit stepSucceeded("install-deps");
	succeed();
}

// Manually included -- see the comment in PythonToolchainBootstrapper.cpp.
#include "moc_PackageDependencyInstaller.cpp"
