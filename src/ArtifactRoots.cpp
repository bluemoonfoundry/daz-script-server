#include "ArtifactRoots.h"
#include <QtCore/qdir.h>
#include <QtCore/qfile.h>
#include <QtCore/qfileinfo.h>
#include <vector>

#include "QtCompat.h"

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <io.h>
#else
#include <fcntl.h>
#include <limits.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/param.h>
#endif

ArtifactRoots::ArtifactRoots()
    : m_bEnabled(true)
{
}

QStringList ArtifactRoots::defaultRoots()
{
    QStringList roots;
    roots << QDir::tempPath();
    roots << QtCompat::writableLocation(QtCompat::Documents)
          << QtCompat::writableLocation(QtCompat::Pictures)
          << QtCompat::writableLocation(QtCompat::Desktop)
          << QtCompat::writableLocation(QtCompat::Downloads);
    QStringList out;
    const QString home = QDir::cleanPath(QDir::homePath());
    for (int i = 0; i < roots.size(); ++i) {
        const QString r = QDir::cleanPath(roots[i]);
        // A platform that reports no such folder may answer with the home
        // folder itself; never let that widen the boundary to all of home.
        if (r.isEmpty() || r.compare(home, Qt::CaseInsensitive) == 0) continue;
        if (!out.contains(r, Qt::CaseInsensitive)) out << r;
    }
    return out;
}

void ArtifactRoots::configure(const QString& rawList, QStringList* outWarnings)
{
    m_sRawList = rawList;

    QStringList given;
    const QStringList parts = rawList.split(';');
    for (int i = 0; i < parts.size(); ++i) {
        const QString p = parts[i].trimmed();
        if (!p.isEmpty()) given << QDir::cleanPath(QDir::fromNativeSeparators(p));
    }
    if (given.isEmpty()) given = defaultRoots();

    QStringList effective;
    QStringList resolved;
    for (int i = 0; i < given.size(); ++i) {
        if (!QDir::isAbsolutePath(given[i])) {
            if (outWarnings) *outWarnings << QString("artifact root '%1' is not absolute; ignored").arg(given[i]);
            continue;
        }
        const QString real = realPathOfDir(given[i]);
        if (real.isEmpty()) {
            if (outWarnings) *outWarnings << QString("artifact root '%1' does not exist; ignored").arg(given[i]);
            continue;
        }
        effective << given[i];
        resolved << real;
    }
    m_aEffective = effective;
    m_aResolved  = resolved;
}

bool ArtifactRoots::setDeniedDir(const QString& dir)
{
    m_sDeniedRaw = QDir::cleanPath(dir);
    m_sDenied    = realPathOfDir(m_sDeniedRaw);
    return !m_sDenied.isEmpty();
}

bool ArtifactRoots::deniedDirAllows(const QString& real) const
{
    if (m_sDeniedRaw.isEmpty()) return true;   // nothing to deny
    QString denied = m_sDenied;
    if (denied.isEmpty()) {
        // Unresolved at start (W13): the folder may have been created since,
        // so resolve it now. If it exists but still can't be resolved, we
        // can't tell whether the file is inside it: fail closed.
        denied = realPathOfDir(m_sDeniedRaw);
        if (denied.isEmpty())
            return !QFileInfo(m_sDeniedRaw).exists();
    }
    return !isUnder(real, denied);
}

bool ArtifactRoots::allows(FILE* f) const
{
    const QString real = realPathOf(f);
    if (real.isEmpty()) return false;   // can't tell where it is: refuse
    if (!deniedDirAllows(real)) return false;
    if (!m_bEnabled) return true;
    for (int i = 0; i < m_aResolved.size(); ++i) {
        if (isUnder(real, m_aResolved.at(i))) return true;
    }
    return false;
}

bool ArtifactRoots::isUnder(const QString& path, const QString& root)
{
    // Windows and macOS file systems are case-insensitive by default.
#if defined(_WIN32) || defined(__APPLE__)
    const Qt::CaseSensitivity cs = Qt::CaseInsensitive;
#else
    const Qt::CaseSensitivity cs = Qt::CaseSensitive;
#endif
    if (root.isEmpty() || !path.startsWith(root, cs)) return false;
    if (path.size() == root.size()) return true;
    const QChar last = root.at(root.size() - 1);
    if (last == QChar('/') || last == QChar('\\')) return true;   // "C:\" or "/"
    const QChar next = path.at(root.size());
    return next == QChar('/') || next == QChar('\\');
}

#ifdef _WIN32

using QtCompat::fromWide;

static QString finalPathOfHandle(HANDLE h)
{
    if (h == INVALID_HANDLE_VALUE || h == 0) return QString();
    const DWORD flags = FILE_NAME_NORMALIZED | VOLUME_NAME_DOS;
    wchar_t stackBuf[MAX_PATH + 1];
    const DWORD n = GetFinalPathNameByHandleW(h, stackBuf, MAX_PATH + 1, flags);
    if (n == 0) return QString();
    if (n <= MAX_PATH) return fromWide(stackBuf, int(n));
    // Long path: n is the required size including the terminator.
    std::vector<wchar_t> big(n);
    const DWORD m = GetFinalPathNameByHandleW(h, &big[0], n, flags);
    if (m == 0 || m >= n) return QString();
    return fromWide(&big[0], int(m));
}

QString ArtifactRoots::realPathOf(FILE* f)
{
    if (!f) return QString();
    return finalPathOfHandle(reinterpret_cast<HANDLE>(_get_osfhandle(_fileno(f))));
}

QString ArtifactRoots::realPathOfDir(const QString& dir)
{
    const QString native = QDir::toNativeSeparators(dir);
    // FILE_FLAG_BACKUP_SEMANTICS is required to open a directory handle.
    HANDLE h = CreateFileW(reinterpret_cast<const wchar_t*>(native.utf16()), 0,
                           FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, 0,
                           OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, 0);
    if (h == INVALID_HANDLE_VALUE) return QString();
    BY_HANDLE_FILE_INFORMATION info;
    const bool isDir = GetFileInformationByHandle(h, &info)
                    && (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY);
    const QString real = isDir ? finalPathOfHandle(h) : QString();
    CloseHandle(h);
    return real;
}

#else

QString ArtifactRoots::realPathOf(FILE* f)
{
    if (!f) return QString();
#if defined(__APPLE__)
    char buf[MAXPATHLEN];
    if (fcntl(fileno(f), F_GETPATH, buf) == -1) return QString();
    return QString::fromUtf8(buf);
#elif defined(__linux__)
    char link[64];
    snprintf(link, sizeof(link), "/proc/self/fd/%d", fileno(f));
    char buf[PATH_MAX];
    const ssize_t n = readlink(link, buf, sizeof(buf) - 1);
    if (n <= 0) return QString();
    buf[n] = 0;
    return QString::fromUtf8(buf);
#else
    return QString();   // unknown platform: refuse rather than guess
#endif
}

QString ArtifactRoots::realPathOfDir(const QString& dir)
{
    const QByteArray local = QFile::encodeName(dir);
    char buf[PATH_MAX];
    if (!realpath(local.constData(), buf)) return QString();
    if (!QFileInfo(QString::fromUtf8(buf)).isDir()) return QString();
    return QString::fromUtf8(buf);
}

#endif
