#pragma once
#include <QtCore/qbytearray.h>
#include <QtCore/qmap.h>
#include <QtCore/qmutex.h>

// ─── IdempotencyCache ────────────────────────────────────────────────────────
//
// Remembers the response to a job submission sent with an Idempotency-Key so
// a client that retries after a timeout gets the original request_id back
// instead of starting a second job.
//
// Keys are scoped by route ("POST /render\n<key>"), so the same key on two
// routes never collides. Each entry also stores a fingerprint (SHA-1 of the
// scoped key + request body): reusing a key with a different body is a client
// bug and is rejected rather than silently replayed.
//
// Lifecycle of a key:
//   begin()  -> PROCEED   (first sighting; entry recorded as in flight)
//            -> IN_FLIGHT (first request still being handled)
//            -> REPLAY    (completed earlier; outStatus/outBody filled)
//            -> MISMATCH  (same key, different fingerprint)
//   complete() stores a 2xx response for replay; any other status drops the
//   entry so a retry can try again (a 503 "queue full" must not stick).
//
// The cache is in memory only: it does not survive a server restart, which
// clients detect through the changed server_instance_id.
//
// THREADING: every method locks m_mutex; safe from raw httplib worker threads
// (QMap/QByteArray/QCryptographicHash are reentrant Qt Core value classes).
class IdempotencyCache {
public:
    enum Outcome { PROCEED, IN_FLIGHT, REPLAY, MISMATCH };

    static const int    MAX_KEY_LENGTH = 255;
    static const int    DEFAULT_MAX_ENTRIES = 1000;
    static const qint64 DEFAULT_TTL_MS = 60LL * 60LL * 1000LL; // matches async job TTL

    IdempotencyCache();

    // Key syntax: 1..MAX_KEY_LENGTH printable ASCII characters (0x21-0x7E).
    static bool isValidKey(const QByteArray& key);

    // scopedKey = method + " " + path + "\n" + client key.
    static QByteArray scopedKey(const QByteArray& method, const QByteArray& path,
                                const QByteArray& key);
    static QByteArray fingerprint(const QByteArray& scopedKey, const QByteArray& body);

    Outcome begin(const QByteArray& scopedKey, const QByteArray& fingerprint,
                  int& outStatus, QByteArray& outBody);
    void    complete(const QByteArray& scopedKey, int status, const QByteArray& body);

    void clear();
    int  ttlSeconds() const { return (int)(m_ttlMs / 1000); }

    // Test/config hooks; not guarded (set before the server starts).
    void setTtlMs(qint64 ms)     { m_ttlMs = ms; }
    void setMaxEntries(int n)    { m_maxEntries = n; }

private:
    struct Entry {
        Entry() : done(false), status(0), createdAt(0) {}
        QByteArray fingerprint;
        bool       done;
        int        status;
        QByteArray body;
        qint64     createdAt;
    };

    void purgeLocked(qint64 now);

    QMap<QByteArray, Entry> m_entries;
    mutable QMutex          m_mutex;
    qint64                  m_ttlMs;
    int                     m_maxEntries;
};
