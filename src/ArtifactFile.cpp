#include "ArtifactFile.h"
#include <QtCore/qbytearray.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <cstring>

#ifdef _WIN32
#include <io.h>
#endif

namespace ArtifactFile {

bool isValidId(const char* s, size_t len)
{
    if (!s || len == 0 || len > 64) return false;
    for (size_t i = 0; i < len; ++i) {
        const char c = s[i];
        const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
                     || (c >= '0' && c <= '9') || c == '-' || c == '_';
        if (!ok) return false;
    }
    return true;
}

static bool isSep(QChar c) { return c == QChar('/') || c == QChar('\\'); }

bool isServablePath(const QString& path)
{
    const int n = path.size();
    if (n == 0 || path.contains(QChar(0))) return false;

#ifdef _WIN32
    // "C:/..." or "C:\..."; "\\server\share\..." (UNC). Reject "\\?\" and
    // "\\.\" device namespaces, and drive-relative "C:foo".
    int start;
    if (n >= 3 && path[0].isLetter() && path[1] == QChar(':') && isSep(path[2])) {
        start = 3;
    } else if (n >= 3 && isSep(path[0]) && isSep(path[1])
               && path[2] != QChar('?') && path[2] != QChar('.')) {
        start = 2;
    } else {
        return false;
    }
#else
    if (path[0] != QChar('/')) return false;
    int start = 1;
#endif

    // Walk the segments: "." and ".." are never allowed, even where they would
    // normalise back inside the same directory.
    int segStart = start;
    for (int i = start; i <= n; ++i) {
        if (i == n || isSep(path[i])) {
            const int len = i - segStart;
            if (len == 1 && path[segStart] == QChar('.')) return false;
            if (len == 2 && path[segStart] == QChar('.') && path[segStart + 1] == QChar('.'))
                return false;
            segStart = i + 1;
        }
    }
    return !isSep(path[n - 1]);
}

static FILE* openRaw(const QString& path)
{
#ifdef _WIN32
    // utf16() is a pointer into the QString itself (no CRT allocation).
    return _wfopen(reinterpret_cast<const wchar_t*>(path.utf16()), L"rb");
#else
    const QByteArray local = path.toUtf8();
    return std::fopen(local.constData(), "rb");
#endif
}

OpenStatus openForRead(const QString& path, FILE** outFile, qint64* outSize)
{
    *outFile = 0;
    *outSize = 0;
    if (!isServablePath(path)) return OPEN_PATH_REJECTED;

    FILE* f = openRaw(path);
    if (!f) return OPEN_MISSING;

#ifdef _WIN32
    struct _stat64 st;
    const int rc = _fstat64(_fileno(f), &st);
    const bool regular = rc == 0 && (st.st_mode & _S_IFMT) == _S_IFREG;
#else
    struct stat st;
    const int rc = fstat(fileno(f), &st);
    const bool regular = rc == 0 && S_ISREG(st.st_mode);
#endif
    if (!regular) {
        std::fclose(f);
        return rc == 0 ? OPEN_NOT_REGULAR : OPEN_MISSING;
    }
    *outFile = f;
    *outSize = (qint64)st.st_size;
    return OPEN_OK;
}

qint64 sizeOf(const QString& path)
{
    FILE*  f = 0;
    qint64 size = 0;
    if (openForRead(path, &f, &size) != OPEN_OK) return -1;
    std::fclose(f);
    return size;
}

bool seek(FILE* f, qint64 offset)
{
#ifdef _WIN32
    return _fseeki64(f, offset, SEEK_SET) == 0;
#else
    return fseeko(f, (off_t)offset, SEEK_SET) == 0;
#endif
}

const char* contentTypeFor(const QString& path)
{
    const int dot = path.lastIndexOf(QChar('.'));
    const int sep = qMax(path.lastIndexOf(QChar('/')), path.lastIndexOf(QChar('\\')));
    if (dot < 0 || dot < sep) return "application/octet-stream";
    const QString ext = path.mid(dot + 1).toLower();

    struct Entry { const char* ext; const char* type; };
    static const Entry kTypes[] = {
        { "png",  "image/png" },
        { "jpg",  "image/jpeg" },
        { "jpeg", "image/jpeg" },
        { "webp", "image/webp" },
        { "gif",  "image/gif" },
        { "bmp",  "image/bmp" },
        { "tif",  "image/tiff" },
        { "tiff", "image/tiff" },
        { "exr",  "image/x-exr" },
        { "hdr",  "image/vnd.radiance" },
        { "svg",  "image/svg+xml" },
        { "mp4",  "video/mp4" },
        { "webm", "video/webm" },
        { "mov",  "video/quicktime" },
        { "avi",  "video/x-msvideo" },
        { "wav",  "audio/wav" },
        { "mp3",  "audio/mpeg" },
        { "json", "application/json" },
        { "jsonl","application/x-ndjson" },
        { "txt",  "text/plain; charset=utf-8" },
        { "log",  "text/plain; charset=utf-8" },
        { "csv",  "text/csv; charset=utf-8" },
        { "xml",  "application/xml" },
        { "zip",  "application/zip" },
        { "pdf",  "application/pdf" },
        { "obj",  "model/obj" },
        { "mtl",  "model/mtl" },
        { "fbx",  "application/octet-stream" },
        { "glb",  "model/gltf-binary" },
        { "gltf", "model/gltf+json" },
        { "usd",  "model/vnd.usd" },
        { "usda", "model/vnd.usda" },
        { "usdc", "model/vnd.usd" },
        { "usdz", "model/vnd.usdz+zip" },
        { "duf",  "application/json" },
        { "dsf",  "application/json" },
    };
    for (size_t i = 0; i < sizeof(kTypes) / sizeof(kTypes[0]); ++i) {
        if (ext == QLatin1String(kTypes[i].ext)) return kTypes[i].type;
    }
    return "application/octet-stream";
}

QString baseName(const QString& path)
{
    const int sep = qMax(path.lastIndexOf(QChar('/')), path.lastIndexOf(QChar('\\')));
    return path.mid(sep + 1);
}

QByteArray contentDisposition(const QString& path)
{
    const QByteArray utf8 = baseName(path).toUtf8();

    QByteArray fallback;
    QByteArray encoded;
    static const char hex[] = "0123456789ABCDEF";
    for (int i = 0; i < utf8.size(); ++i) {
        const unsigned char c = (unsigned char)utf8[i];
        const bool safeQuoted = c >= 0x20 && c < 0x7f && c != '"' && c != '\\';
        fallback.append(safeQuoted ? (char)c : '_');

        // RFC 5987 attr-char
        const bool attr = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
                       || (c >= '0' && c <= '9') || std::strchr("!#$&+-.^_`|~", c);
        if (attr && c != 0) {
            encoded.append((char)c);
        } else {
            encoded.append('%');
            encoded.append(hex[c >> 4]);
            encoded.append(hex[c & 0x0f]);
        }
    }
    if (fallback.isEmpty()) fallback = "artifact";

    QByteArray v("inline; filename=\"");
    v += fallback;
    v += "\"";
    if (!encoded.isEmpty()) {
        v += "; filename*=UTF-8''";
        v += encoded;
    }
    return v;
}

} // namespace ArtifactFile
