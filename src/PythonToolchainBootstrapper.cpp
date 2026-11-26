#include "PythonToolchainBootstrapper.h"

#include "FileSha256.h"
#include "PackagePaths.h"
#include "PortableFs.h"
#include "miniz.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QProcessEnvironment>

#include <cstring>

namespace {

// The one uv release this plugin installs (daz-script-server-yau7.4.6).
// Bump kUvVersion and every sha256 below together -- see the header.
const char *const kUvVersion = "0.13.7";

struct UvAsset {
	const char *name;              // release asset file name
	const char *sha256;            // lowercase hex, from <name>.sha256
	const char *binaryInArchive;   // path of the uv binary inside the archive
};

#if defined(Q_OS_WIN)
const UvAsset kUvAsset = {
	"uv-x86_64-pc-windows-msvc.zip",
	"0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021",
	"uv.exe",
};
#elif defined(Q_OS_MAC) && (defined(__aarch64__) || defined(__arm64__))
const UvAsset kUvAsset = {
	"uv-aarch64-apple-darwin.tar.gz",
	"81b811b57e4624df7ed3aac148e0359100d9962f3d9dce00aec533dc2e086731",
	"uv-aarch64-apple-darwin/uv",
};
#elif defined(Q_OS_MAC)
const UvAsset kUvAsset = {
	"uv-x86_64-apple-darwin.tar.gz",
	"20c47e4c1f630b8abaff8c291fa9b9aa300fef92c4fbff95adf198b55287cda7",
	"uv-x86_64-apple-darwin/uv",
};
#else
#error "PythonToolchainBootstrapper: no pinned uv release asset for this platform"
#endif

QString uvDownloadUrl() {
	return QString::fromLatin1("https://github.com/astral-sh/uv/releases/download/%1/%2")
		.arg(QLatin1String(kUvVersion), QLatin1String(kUvAsset.name));
}

// curl by absolute path, never via PATH or a shell: the URL and output path
// go to it as argv entries, so nothing is parsed by a command interpreter.
// Windows 10 1803+ ships curl.exe in System32 (DAZ Studio requires Win10+).
QString curlPath() {
#ifdef Q_OS_WIN
	QString systemRoot = QProcessEnvironment::systemEnvironment().value("SystemRoot");
	if (systemRoot.isEmpty()) {
		systemRoot = QString::fromLatin1("C:\\Windows");
	}
	return QDir(systemRoot).filePath("System32/curl.exe");
#else
	return QString::fromLatin1("/usr/bin/curl");
#endif
}

} // namespace

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
// download pinned archive → verify SHA-256 → extract uv → move into bin/.
// Every failure path removes the download and staging dir.

void PythonToolchainBootstrapper::installUv() {
	if (QFileInfo(PackagePaths::uvBinaryPath()).exists()) {
		installPython();
		return;
	}

	emit stepStarted("install-uv");

	const QString curl = curlPath();
	if (!QFileInfo(curl).isFile()) {
		fail("install-uv", QString::fromLatin1("curl not found at %1").arg(curl));
		return;
	}

	const QDir binDir(QDir(PackagePaths::baseDir()).filePath("bin"));
	m_uvArchivePath = binDir.filePath(QString::fromLatin1("%1.download").arg(QLatin1String(kUvAsset.name)));
	m_uvStagingDir = binDir.filePath("uv-staging");
	cleanUpUvDownload();

	m_process = new QProcess(this);
	// QStringList() << ... , not a brace-init list: QStringList's
	// initializer-list constructor is Qt5+ only (SDK4/Qt4.8 build).
	// --proto/--proto-redir =https: no plain-HTTP hop anywhere in GitHub's
	// redirect to its asset CDN. -f: an HTTP error is a failure, not a body.
	const QStringList arguments = QStringList()
		<< "--fail" << "--silent" << "--show-error" << "--location"
		<< "--proto" << "=https" << "--proto-redir" << "=https"
		<< "--retry" << "2"
		<< "--output" << m_uvArchivePath
		<< uvDownloadUrl();

	connect(m_process, SIGNAL(finished(int, QProcess::ExitStatus)),
	        this, SLOT(onDownloadUvFinished(int, QProcess::ExitStatus)));
	m_process->start(curl, arguments);
}

void PythonToolchainBootstrapper::onDownloadUvFinished(int exitCode, QProcess::ExitStatus status) {
	if (status != QProcess::NormalExit || exitCode != 0 || !QFileInfo(m_uvArchivePath).isFile()) {
		cleanUpUvDownload();
		fail("install-uv", m_process);
		return;
	}

	// The checksum gate: nothing from the archive is extracted, let alone
	// executed, unless it is byte-for-byte the pinned release asset.
	QString error;
	const QByteArray actual = FileSha256::hexDigest(m_uvArchivePath, &error);
	if (actual.isEmpty()) {
		cleanUpUvDownload();
		fail("install-uv", QString::fromLatin1("could not hash downloaded uv archive: %1").arg(error));
		return;
	}
	if (actual != QByteArray(kUvAsset.sha256)) {
		cleanUpUvDownload();
		fail("install-uv", QString::fromLatin1("uv %1 archive %2 failed SHA-256 verification "
		                                       "(expected %3, got %4); not installing it")
			.arg(QLatin1String(kUvVersion), QLatin1String(kUvAsset.name),
			     QLatin1String(kUvAsset.sha256), QString::fromLatin1(actual)));
		return;
	}

	extractUv();
}

void PythonToolchainBootstrapper::extractUv() {
	if (!QDir().mkpath(m_uvStagingDir)) {
		cleanUpUvDownload();
		fail("install-uv", QString::fromLatin1("could not create %1").arg(m_uvStagingDir));
		return;
	}

#ifdef Q_OS_WIN
	// .zip: pull the one entry out with the vendored miniz, in-process.
	mz_zip_archive zip;
	memset(&zip, 0, sizeof(zip));
	if (!mz_zip_reader_init_file(&zip, m_uvArchivePath.toUtf8().constData(), 0)) {
		cleanUpUvDownload();
		fail("install-uv", QString::fromLatin1("could not open uv archive %1").arg(m_uvArchivePath));
		return;
	}
	size_t size = 0;
	void *data = mz_zip_reader_extract_file_to_heap(&zip, kUvAsset.binaryInArchive, &size, 0);
	mz_zip_reader_end(&zip);
	if (!data) {
		cleanUpUvDownload();
		fail("install-uv", QString::fromLatin1("%1 not found in uv archive").arg(QLatin1String(kUvAsset.binaryInArchive)));
		return;
	}
	const QByteArray bytes(static_cast<const char *>(data), static_cast<int>(size));
	mz_free(data);

	const QString extracted = QDir(m_uvStagingDir).filePath(QLatin1String(kUvAsset.binaryInArchive));
	QFile out(extracted);
	const bool written = out.open(QIODevice::WriteOnly)
		&& out.write(bytes) == bytes.size()
		&& out.flush()
		&& out.error() == QFile::NoError;
	out.close();
	if (!written) {
		const QString reason = out.errorString();
		cleanUpUvDownload();
		fail("install-uv", QString::fromLatin1("could not write %1: %2").arg(extracted, reason));
		return;
	}
	finishInstallUv(extracted);
#else
	// .tar.gz: the system tar, asked for just the uv entry. Async like every
	// other step so the main thread never blocks on it.
	m_process = new QProcess(this);
	const QStringList arguments = QStringList()
		<< "-xzf" << m_uvArchivePath << "-C" << m_uvStagingDir
		<< QString::fromLatin1(kUvAsset.binaryInArchive);
	connect(m_process, SIGNAL(finished(int, QProcess::ExitStatus)),
	        this, SLOT(onExtractUvFinished(int, QProcess::ExitStatus)));
	m_process->start("/usr/bin/tar", arguments);
#endif
}

void PythonToolchainBootstrapper::onExtractUvFinished(int exitCode, QProcess::ExitStatus status) {
	const QString extracted = QDir(m_uvStagingDir).filePath(QLatin1String(kUvAsset.binaryInArchive));
	if (status != QProcess::NormalExit || exitCode != 0 || !QFileInfo(extracted).isFile()) {
		cleanUpUvDownload();
		fail("install-uv", m_process);
		return;
	}
	finishInstallUv(extracted);
}

void PythonToolchainBootstrapper::finishInstallUv(const QString &extractedBinary) {
	// Owner-only read/write/execute, set before the move so uv is never
	// visible at its final path without being runnable.
	QFile::setPermissions(extractedBinary,
		QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner | QFile::ReadUser | QFile::WriteUser | QFile::ExeUser);

	const QString target = PackagePaths::uvBinaryPath();
	QFile::remove(target);  // only reached when it was absent; drops a dangling leftover
	const bool moved = QFile::rename(extractedBinary, target);
	cleanUpUvDownload();
	if (!moved || !QFileInfo(target).isFile()) {
		fail("install-uv", QString::fromLatin1("could not move uv into %1").arg(target));
		return;
	}
	emit stepSucceeded("install-uv");
	installPython();
}

void PythonToolchainBootstrapper::cleanUpUvDownload() {
	if (!m_uvArchivePath.isEmpty()) {
		QFile::remove(m_uvArchivePath);
	}
	if (!m_uvStagingDir.isEmpty()) {
		PortableFs::removeRecursively(m_uvStagingDir);
	}
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
