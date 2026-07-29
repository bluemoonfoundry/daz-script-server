#include "PythonToolchainBootstrapper.h"

#include "PackagePaths.h"

#include <QDir>
#include <QFileInfo>
#include <QProcessEnvironment>

PythonToolchainBootstrapper::PythonToolchainBootstrapper(QObject *parent) : QObject(parent) {}

void PythonToolchainBootstrapper::ensureReady() {
	if (!PackagePaths::ensureBaseDirExists()) {
		fail("ensure-base-dir", QString::fromLatin1("could not create %1").arg(PackagePaths::baseDir()));
		return;
	}
	installUv();
}

void PythonToolchainBootstrapper::fail(const QString &step, const QString &message) {
	emit stepFailed(step, message);
}

void PythonToolchainBootstrapper::fail(const QString &step, QProcess *process) {
	const QString message = QString::fromUtf8(process->readAllStandardError());
	emit stepFailed(step, message.isEmpty() ? process->errorString() : message);
}

// ─── Step 1: install uv itself ────────────────────────────────────────────────

void PythonToolchainBootstrapper::installUv() {
	if (QFileInfo(PackagePaths::uvBinaryPath()).exists()) {
		installPython();
		return;
	}

	emit stepStarted("install-uv");

	m_process = new QProcess(this);

	QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
	env.insert("UV_INSTALL_DIR", QDir(PackagePaths::baseDir()).filePath("bin"));
	env.insert("UV_NO_MODIFY_PATH", "1");
	m_process->setProcessEnvironment(env);

#ifdef Q_OS_WIN
	const QString program = "powershell.exe";
	// QStringList() << ... , not a brace-init list: QStringList's
	// initializer-list constructor is Qt5+ only (SDK4/Qt4.8 build).
	const QStringList arguments = QStringList()
		<< "-NoProfile" << "-ExecutionPolicy" << "Bypass" << "-Command"
		<< "irm https://astral.sh/uv/install.ps1 | iex";
#else
	const QString program = "/bin/sh";
	const QStringList arguments = QStringList() << "-c" << "curl -LsSf https://astral.sh/uv/install.sh | sh";
#endif

	connect(m_process, SIGNAL(finished(int, QProcess::ExitStatus)),
	        this, SLOT(onInstallUvFinished(int, QProcess::ExitStatus)));
	m_process->start(program, arguments);
}

void PythonToolchainBootstrapper::onInstallUvFinished(int exitCode, QProcess::ExitStatus status) {
	if (status != QProcess::NormalExit || exitCode != 0 || !QFileInfo(PackagePaths::uvBinaryPath()).exists()) {
		fail("install-uv", m_process);
		return;
	}
	emit stepSucceeded("install-uv");
	installPython();
}

// ─── Step 2: install Python 3.11 via uv ──────────────────────────────────────
// The last step: unlike daz-python-bridge's UvBootstrapper (which this is
// adapted from), there is no shared venv to create here -- each package's
// venv is created lazily by PackageDependencyInstaller against this shared
// Python 3.11 build, not eagerly by this class.

void PythonToolchainBootstrapper::installPython() {
	emit stepStarted("install-python");

	m_process = new QProcess(this);
	const QStringList arguments = QStringList() << "python" << "install" << "3.11";

	connect(m_process, SIGNAL(finished(int, QProcess::ExitStatus)),
	        this, SLOT(onInstallPythonFinished(int, QProcess::ExitStatus)));
	m_process->start(PackagePaths::uvBinaryPath(), arguments);
}

void PythonToolchainBootstrapper::onInstallPythonFinished(int exitCode, QProcess::ExitStatus status) {
	if (status != QProcess::NormalExit || exitCode != 0) {
		fail("install-python", m_process);
		return;
	}
	emit stepSucceeded("install-python");
	emit ready();
}

// Manually included -- CMAKE_AUTOMOC_MOC_OPTIONS -i (top-level CMakeLists.txt)
// is set project-wide, which suppresses moc's default self-include of this
// class's own header for every Q_OBJECT class, not just pluginmain.cpp's
// inline one it was added for. Same pattern DzScriptServerPane.cpp/
// SceneEventBroker.cpp already use.
#include "moc_PythonToolchainBootstrapper.cpp"
