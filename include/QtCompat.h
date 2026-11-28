#pragma once
// Qt 4.8 (Studio 4 SDK) vs Qt 6 (Studio 6 SDK) API differences, in one place.
//
// Only API spelling lives here: the same behaviour written two ways. Real
// Studio 4 / Studio 6 behaviour splits (async enqueue, the print() shim, the
// SDK version tag) stay as DAZ_SDK_MAJOR_VERSION blocks where they happen, so
// the condition keeps documenting why the paths differ.

#include <QtCore/qstring.h>
#include <QtCore/qstringlist.h>
#include <QtCore/qtextstream.h>
#include <QtCore/quuid.h>

#if DAZ_SDK_MAJOR_VERSION >= 6
#include <QtCore/qregularexpression.h>
#include <QtCore/qstandardpaths.h>
#else
#include <QtCore/qregexp.h>
#include <QtCore/qdir.h>
#include <QtGui/qdesktopservices.h>
#endif

namespace QtCompat {

// QString::split() empty-part behaviour (moved from QString:: to Qt:: in Qt 5.14).
#if DAZ_SDK_MAJOR_VERSION >= 6
static const Qt::SplitBehavior SkipEmptyParts = Qt::SkipEmptyParts;
#else
static const QString::SplitBehavior SkipEmptyParts = QString::SkipEmptyParts;
#endif

// Whole-string regex match, the same on both Qt versions: the pattern must
// match all of the input. A PCRE "$" also matches before a trailing "\n", so
// a plain ^...$ QRegularExpression accepts "name\n"; anchoredPattern() (\A...\z)
// doesn't, matching QRegExp::exactMatch(). ^/$ inside the pattern are harmless.
//
// Safe as a shared static const: QRegExp keeps match state in the object, so
// the Qt 4 path matches on a per-call copy (Qt 4 caches the compiled pattern).
class WholeMatch {
public:
	explicit WholeMatch(const QString& pattern)
#if DAZ_SDK_MAJOR_VERSION >= 6
		: m_rx(QRegularExpression::anchoredPattern(pattern)) {}
#else
		: m_pattern(pattern) {}
#endif

	bool matches(const QString& s) const { return match(s, 0); }

	// On a match, *captures (if given) gets the whole match then each group.
	bool match(const QString& s, QStringList* captures) const {
#if DAZ_SDK_MAJOR_VERSION >= 6
		const QRegularExpressionMatch m = m_rx.match(s);
		if (!m.hasMatch()) return false;
		if (captures) *captures = m.capturedTexts();
#else
		QRegExp rx(m_pattern);
		if (!rx.exactMatch(s)) return false;
		if (captures) *captures = rx.capturedTexts();
#endif
		return true;
	}

private:
#if DAZ_SDK_MAJOR_VERSION >= 6
	QRegularExpression m_rx;
#else
	QString m_pattern;
#endif
};

// QUuid as 8-4-4-4-12 hex without braces (QUuid::WithoutBraces is Qt 5.11+).
inline QString uuidWithoutBraces() {
#if DAZ_SDK_MAJOR_VERSION >= 6
	return QUuid::createUuid().toString(QUuid::WithoutBraces);
#else
	const QString withBraces = QUuid::createUuid().toString();
	return withBraces.mid(1, withBraces.length() - 2);
#endif
}

// Qt 6 QTextStream is UTF-8 by default and setCodec() is gone; Qt 4 needs it.
inline void setUtf8(QTextStream& stream) {
#if DAZ_SDK_MAJOR_VERSION >= 6
	(void)stream;
#else
	stream.setCodec("UTF-8");
#endif
}

// Per-user folders (QStandardPaths is Qt 5+; Qt 4 has QDesktopServices).
enum Location { Documents, Pictures, Desktop, Downloads, AppData };

inline QString writableLocation(Location where) {
#if DAZ_SDK_MAJOR_VERSION >= 6
	switch (where) {
	case Documents: return QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation);
	case Pictures:  return QStandardPaths::writableLocation(QStandardPaths::PicturesLocation);
	case Desktop:   return QStandardPaths::writableLocation(QStandardPaths::DesktopLocation);
	case Downloads: return QStandardPaths::writableLocation(QStandardPaths::DownloadLocation);
	case AppData:   return QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
	}
#else
	switch (where) {
	case Documents: return QDesktopServices::storageLocation(QDesktopServices::DocumentsLocation);
	case Pictures:  return QDesktopServices::storageLocation(QDesktopServices::PicturesLocation);
	case Desktop:   return QDesktopServices::storageLocation(QDesktopServices::DesktopLocation);
	case Downloads: return QDir::homePath() + "/Downloads";   // Qt 4 has no DownloadLocation
	case AppData:   return QDesktopServices::storageLocation(QDesktopServices::DataLocation);
	}
#endif
	return QString();
}

#ifdef _WIN32
// Studio 4's Qt 4.8 was built with wchar_t as unsigned short, so its
// QString::fromWCharArray(const wchar_t*) export doesn't link against our
// native-wchar_t build; read the UTF-16 directly there.
inline QString fromWide(const wchar_t* s, int n) {
#if DAZ_SDK_MAJOR_VERSION >= 6
	return QString::fromWCharArray(s, n);
#else
	return QString::fromUtf16(reinterpret_cast<const ushort*>(s), n);
#endif
}
#endif

} // namespace QtCompat
