#pragma once
// Thumbnails for GET /artifacts/{job_id}/{artifact_id}?thumbnail=<px>.
//
// THREADING: QImage/QImageReader belong to QtGui, and nobody has verified that
// their format plugins are safe on a raw httplib std::thread under Qt 4.8. So
// the HTTP worker does everything that needs no QtGui (validation, reading the
// file with C stdio, the cache lookup) and hands the bytes to the main thread,
// which only decodes, scales and encodes. The worker waits with a timeout:
// while a long job holds the main thread it answers 503 STUDIO_BUSY instead
// of blocking (see DzScriptServerPane::handleThumbnailJob).
//
// CRT: only Qt value types (QByteArray, QString, QStringList) cross between
// threads or live in the cache; no std:: container built by Qt's CRT is ever
// freed by ours (msvcr100/ucrtbase rule).

#include <QtCore/qatomic.h>
#include <QtCore/qbytearray.h>
#include <QtCore/qlist.h>
#include <QtCore/qmap.h>
#include <QtCore/qmutex.h>
#include <QtCore/qsemaphore.h>
#include <QtCore/qstring.h>
#include <QtCore/qstringlist.h>

#include <string>

namespace ArtifactThumbnail {

// Longest edge of the thumbnail, in pixels. Never upscaled past the source.
const int kMinPx = 16;
const int kMaxPx = 1024;

// Source limits: larger files or images are refused (422), not decoded.
const qint64 kMaxSourceBytes = 64 * 1024 * 1024;
const qint64 kMaxSourcePixels = 100LL * 1000 * 1000;

// How long a worker waits for the main thread before answering 503.
const int kMainThreadTimeoutMs = 10000;

enum Format { FORMAT_PNG, FORMAT_JPEG };

const char* contentType(Format f);   // "image/png" / "image/jpeg"
const char* extension(Format f);     // "png" / "jpg"

// Parses ?thumbnail=<px>&format=png|jpeg. On failure returns false and sets
// *error to a message for INVALID_FIELD.
bool parseParams(const std::string& thumbnail, const std::string& format, bool hasFormat,
                 int* outPx, Format* outFormat, std::string* error);

// One thumbnail request crossing from a worker to the main thread. Created
// with two references (worker + main thread); whoever drops the last one
// deletes it, so a worker that times out can leave without waiting.
struct Job {
    Job() : maxPx(0), format(FORMAT_PNG), ok(false), refs(2), abandoned(0) {}

    // Input (set by the worker before posting).
    QByteArray source;
    int        maxPx;
    Format     format;

    // Output (set by the main thread before done.release()).
    bool       ok;
    QByteArray image;
    QString    error;

    QSemaphore done;
    QAtomicInt refs;
    QAtomicInt abandoned;   // 1 once the worker gave up; main thread skips work
};

// Drop one reference; deletes the job on the last one.
void release(Job* job);

// MAIN THREAD ONLY. Decodes job->source, scales it to fit maxPx, encodes it.
// Does nothing if the worker already abandoned the job. Always signals
// job->done and drops the main thread's reference.
void run(Job* job);

// MAIN THREAD ONLY. Lower-case file extensions the loaded Qt image plugins
// can read (from QImageReader::supportedImageFormats()), e.g. "png", "jpg".
QStringList readableExtensions();

// True when path's extension is in exts (case-insensitive).
bool extensionIn(const QString& path, const QStringList& exts);

// Small mutex-protected LRU cache of encoded thumbnails, keyed by the source
// path, its size and mtime, and the requested px/format. Safe from any thread.
class Cache {
public:
    explicit Cache(int capacity = 64);
    static QString key(const QString& path, qint64 size, qint64 mtime, int px, Format f);
    bool get(const QString& key, QByteArray* out);
    void put(const QString& key, const QByteArray& image);
    void clear();
private:
    QMutex                   m_mutex;
    QMap<QString, QByteArray> m_entries;
    QStringList              m_order;   // least recently used first
    int                      m_capacity;
};

} // namespace ArtifactThumbnail
