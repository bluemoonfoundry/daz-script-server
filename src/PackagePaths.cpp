#include "PackagePaths.h"

#include <QDir>

// QStandardPaths is Qt5+; Qt 4.8 (SDK4 build) only has
// QDesktopServices::storageLocation() for this, in QtGui rather than
// QtCore -- already linked into this plugin regardless of SDK version.
#if DAZ_SDK_MAJOR_VERSION >= 6
#include <QStandardPaths>
#else
#include <QDesktopServices>
#endif

#ifdef Q_OS_WIN
static const char *kUvBinaryName = "uv.exe";
#else
static const char *kUvBinaryName = "uv";
#endif

QString PackagePaths::baseDir() {
#if DAZ_SDK_MAJOR_VERSION >= 6
	const QString appData = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
#else
	const QString appData = QDesktopServices::storageLocation(QDesktopServices::DataLocation);
#endif
	return QDir(appData).filePath("DazScriptServer");
}

QString PackagePaths::uvBinaryPath() {
	return QDir(baseDir()).filePath(QString::fromLatin1("bin/%1").arg(kUvBinaryName));
}

QString PackagePaths::packagesDir() {
	return QDir(baseDir()).filePath("packages");
}

QString PackagePaths::packageDir(const QString &packageId) {
	return QDir(packagesDir()).filePath(packageId);
}

QString PackagePaths::packageVenvDir(const QString &packageId) {
	return QDir(packageDir(packageId)).filePath("venv");
}

bool PackagePaths::ensureBaseDirExists() {
	QDir dir;
	return dir.mkpath(baseDir()) && dir.mkpath(QDir(baseDir()).filePath("bin"));
}
