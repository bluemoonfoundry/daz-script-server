#pragma once
// Small filesystem helpers portable across Qt4 (SDK4 build) and Qt6.

#include <QDir>
#include <QFile>
#include <QFileInfo>

namespace PortableFs {

// QDir::removeRecursively() is Qt5+ only; Qt 4.8 has no built-in recursive
// delete. Symlinked directories are unlinked, not recursed into, matching
// QDir::removeRecursively()'s own documented behavior.
inline bool removeRecursively(const QString &path) {
#if DAZ_SDK_MAJOR_VERSION >= 6
	return QDir(path).removeRecursively();
#else
	QDir dir(path);
	if (!dir.exists()) {
		return true;
	}
	const QFileInfoList entries = dir.entryInfoList(QDir::NoDotAndDotDot | QDir::AllEntries);
	for (const QFileInfo &entry : entries) {
		if (entry.isDir() && !entry.isSymLink()) {
			if (!removeRecursively(entry.absoluteFilePath())) {
				return false;
			}
		} else if (!QFile::remove(entry.absoluteFilePath())) {
			return false;
		}
	}
	return QDir().rmdir(path);
#endif
}

} // namespace PortableFs
