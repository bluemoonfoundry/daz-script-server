#pragma once
// File access for GET /artifacts/{job_id}/{artifact_id}.
//
// THREADING: everything here runs on raw httplib worker threads. It only uses
// the C runtime (fopen/_wfopen, fstat) and QString's read-only accessors, so it
// never touches thread-affine Qt objects. QString::utf16()/toUtf8() are used
// instead of toStdWString()/toStdString() so no std:: container allocated by
// Qt's CRT is ever freed by ours (see the msvcr100/ucrtbase mismatch rule).

#include <QtCore/qstring.h>
#include <QtCore/qglobal.h>
#include <cstdio>

namespace ArtifactFile {

// Artifact and job IDs in the URL: 1-64 chars of [A-Za-z0-9_-]. Anything else
// (dots, slashes, percent-escapes) is rejected before any lookup happens.
bool isValidId(const char* s, size_t len);

// True when a declared output path may be served: absolute (drive-letter or
// UNC on Windows, '/' elsewhere), no NUL, and no "." or ".." path segment.
bool isServablePath(const QString& path);

enum OpenStatus {
    OPEN_OK,
    OPEN_PATH_REJECTED,   // isServablePath() failed
    OPEN_MISSING,         // file does not exist / cannot be opened
    OPEN_NOT_REGULAR      // directory, device, pipe ...
};

// Opens a declared output for reading. On OPEN_OK, *outFile is an open FILE*
// the caller must fclose(), and *outSize is its size in bytes. When outMtime
// is given it receives the modification time (seconds since the epoch).
OpenStatus openForRead(const QString& path, FILE** outFile, qint64* outSize,
                       qint64* outMtime = 0);

// Size of a declared output without keeping it open; -1 when unavailable.
qint64 sizeOf(const QString& path);

// Seek on a FILE* with 64-bit offsets.
bool seek(FILE* f, qint64 offset);

// MIME type by file extension; "application/octet-stream" when unknown.
const char* contentTypeFor(const QString& path);

// Final path component of a '/' or '\' separated path.
QString baseName(const QString& path);

// Content-Disposition value for the file's base name:
//   inline; filename="ascii_fallback"; filename*=UTF-8''percent-encoded
// The quoted fallback replaces non-ASCII, quotes, backslashes and controls
// with '_' so the header can't be broken by a hostile file name.
QByteArray contentDisposition(const QString& path);

} // namespace ArtifactFile
