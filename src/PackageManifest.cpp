#include "PackageManifest.h"

#include <QDir>
#include <QFileInfo>

// QRegularExpression is Qt5+; Qt 4.8 (SDK4 build) only has the older QRegExp.
#if DAZ_SDK_MAJOR_VERSION >= 6
#include <QRegularExpression>
#else
#include <QRegExp>
#endif

namespace {

// PEP 508 name, optional extras, optional version specifiers. Kept free of
// backslash escapes other than "\\[" / "\\]" so tests/test_package_manifest.py
// can lift it from this file and exercise it with Python's re module.
const char *kDependencyPattern =
	"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?"
	"( *\\[ *[A-Za-z0-9][A-Za-z0-9._-]*( *, *[A-Za-z0-9][A-Za-z0-9._-]*)* *\\])?"
	"( *(===|==|!=|<=|>=|~=|<|>) *[A-Za-z0-9.*+!_-]+"
	"( *, *(===|==|!=|<=|>=|~=|<|>) *[A-Za-z0-9.*+!_-]+)*)?$";

const int kMaxDependencyLength = 256;

bool matchesDependencyPattern(const QString &dependency) {
#if DAZ_SDK_MAJOR_VERSION >= 6
	static const QRegularExpression pattern(QString::fromLatin1(kDependencyPattern));
	return pattern.match(dependency).hasMatch();
#else
	static const QRegExp pattern(QString::fromLatin1(kDependencyPattern));
	return pattern.exactMatch(dependency);
#endif
}

} // namespace

namespace PackageManifest {

bool isValidDependency(const QString &dependency) {
	if (dependency.isEmpty() || dependency.length() > kMaxDependencyLength) {
		return false;
	}
	return matchesDependencyPattern(dependency);
}

bool readDependencies(const QVariant &value, QStringList &dependencies, QString &errorMessage) {
	dependencies.clear();
	if (!value.isValid() || value.isNull()) {
		return true;
	}
	// QVariant::toStringList() would turn a bare string into a one-item
	// list; the manifest format says array, so require one.
	if (value.type() != QVariant::List) {
		errorMessage = QString::fromLatin1("manifest.json \"dependencies\" must be an array of strings");
		return false;
	}
	const QVariantList items = value.toList();
	for (const QVariant &item : items) {
		const QString dependency = item.toString();
		if (item.type() != QVariant::String || !isValidDependency(dependency)) {
			errorMessage = QString::fromLatin1(
				"manifest.json \"dependencies\" entry is not a plain package requirement "
				"(name[extras] with optional version specifiers): %1").arg(dependency);
			return false;
		}
		dependencies << dependency;
	}
	return true;
}

bool validateEntryPoint(const QString &packageDir, const QString &entryPoint, QString &errorMessage) {
	const QString invalid = QString::fromLatin1(
		"manifest.json \"entryPoint\" must be a relative path to a file inside the package: %1").arg(entryPoint);

	// ':' covers drive-qualified ("C:x", "C:\\x") and stream ("x:ads") forms.
	if (entryPoint.isEmpty() || QDir::isAbsolutePath(entryPoint) ||
		entryPoint.startsWith(QLatin1Char('/')) || entryPoint.startsWith(QLatin1Char('\\')) ||
		entryPoint.contains(QLatin1Char(':'))) {
		errorMessage = invalid;
		return false;
	}

	QString normalized = entryPoint;
	normalized.replace(QLatin1Char('\\'), QLatin1Char('/'));
	const QStringList segments = normalized.split(QLatin1Char('/'));
	for (const QString &segment : segments) {
		if (segment == QLatin1String("..")) {
			errorMessage = invalid;
			return false;
		}
	}

	const QString root = QFileInfo(packageDir).canonicalFilePath();
	const QFileInfo target(QDir(packageDir).filePath(normalized));
	const QString resolved = target.canonicalFilePath();
	if (root.isEmpty() || resolved.isEmpty() || !target.isFile()) {
		errorMessage = QString::fromLatin1("manifest.json \"entryPoint\" file not found in the package: %1").arg(entryPoint);
		return false;
	}
#ifdef Q_OS_WIN
	const Qt::CaseSensitivity cs = Qt::CaseInsensitive;
#else
	const Qt::CaseSensitivity cs = Qt::CaseSensitive;
#endif
	if (!resolved.startsWith(root + QLatin1Char('/'), cs)) {
		errorMessage = invalid;
		return false;
	}
	return true;
}

bool readTimeoutSeconds(const QVariant &value, int &seconds, QString &errorMessage) {
	seconds = kDefaultTimeoutSeconds;
	if (!value.isValid() || value.isNull()) {
		return true;
	}
	const QVariant::Type type = value.type();
	const bool numeric = type == QVariant::Int || type == QVariant::UInt ||
		type == QVariant::LongLong || type == QVariant::ULongLong || type == QVariant::Double;
	const double number = value.toDouble();
	// Range first: casting an out-of-range double to int is undefined.
	if (!numeric || !(number >= 1 && number <= kMaxTimeoutSeconds) ||
		number != static_cast<double>(static_cast<int>(number))) {
		errorMessage = QString::fromLatin1(
			"manifest.json \"timeoutSeconds\" must be a whole number from 1 to %1").arg(kMaxTimeoutSeconds);
		return false;
	}
	seconds = static_cast<int>(number);
	return true;
}

} // namespace PackageManifest
