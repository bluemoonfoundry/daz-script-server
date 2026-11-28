#include "IdempotencyCache.h"
#include <QtCore/qcryptographichash.h>
#include <QtCore/qdatetime.h>

IdempotencyCache::IdempotencyCache()
    : m_ttlMs(DEFAULT_TTL_MS)
    , m_maxEntries(DEFAULT_MAX_ENTRIES)
{}

bool IdempotencyCache::isValidKey(const QByteArray& key)
{
    if (key.isEmpty() || key.size() > MAX_KEY_LENGTH)
        return false;
    for (int i = 0; i < key.size(); ++i) {
        const unsigned char c = static_cast<unsigned char>(key[i]);
        if (c < 0x21 || c > 0x7E)
            return false;
    }
    return true;
}

QByteArray IdempotencyCache::scopedKey(const QByteArray& method, const QByteArray& path,
                                       const QByteArray& key)
{
    return method + " " + path + "\n" + key;
}

QByteArray IdempotencyCache::fingerprint(const QByteArray& scopedKey, const QByteArray& body)
{
    // SHA-1: Qt 4.8 has no SHA-2. This only detects key reuse; not a security boundary.
    QCryptographicHash h(QCryptographicHash::Sha1);
    h.addData(scopedKey);
    h.addData("\n", 1);
    h.addData(body);
    return h.result();
}

void IdempotencyCache::purgeLocked(qint64 now)
{
    QMap<QByteArray, Entry>::iterator it = m_entries.begin();
    while (it != m_entries.end()) {
        // In-flight entries expire too: a handler that never completed (e.g.
        // the server was stopped mid-request) must not wedge the key forever.
        if (now - it.value().createdAt > m_ttlMs)
            it = m_entries.erase(it);
        else
            ++it;
    }
}

IdempotencyCache::Outcome IdempotencyCache::begin(const QByteArray& key,
                                                  const QByteArray& fp,
                                                  int& outStatus, QByteArray& outBody)
{
    const qint64 now = QDateTime::currentMSecsSinceEpoch();
    QMutexLocker lock(&m_mutex);

    QMap<QByteArray, Entry>::iterator it = m_entries.find(key);
    if (it != m_entries.end() && now - it.value().createdAt > m_ttlMs) {
        m_entries.erase(it);
        it = m_entries.end();
    }

    if (it != m_entries.end()) {
        const Entry& e = it.value();
        if (e.fingerprint != fp)
            return MISMATCH;
        if (!e.done)
            return IN_FLIGHT;
        outStatus = e.status;
        outBody   = e.body;
        return REPLAY;
    }

    if (m_entries.size() >= m_maxEntries) {
        purgeLocked(now);
        // Still full: evict the oldest completed entry. If every entry is in
        // flight, proceed without recording (the request is simply not
        // deduplicated) rather than refusing work.
        if (m_entries.size() >= m_maxEntries) {
            QMap<QByteArray, Entry>::iterator oldest = m_entries.end();
            for (QMap<QByteArray, Entry>::iterator j = m_entries.begin(); j != m_entries.end(); ++j) {
                if (j.value().done &&
                    (oldest == m_entries.end() || j.value().createdAt < oldest.value().createdAt))
                    oldest = j;
            }
            if (oldest == m_entries.end())
                return PROCEED;
            m_entries.erase(oldest);
        }
    }

    Entry e;
    e.fingerprint = fp;
    e.createdAt   = now;
    m_entries.insert(key, e);
    return PROCEED;
}

void IdempotencyCache::complete(const QByteArray& key, int status, const QByteArray& body)
{
    QMutexLocker lock(&m_mutex);
    QMap<QByteArray, Entry>::iterator it = m_entries.find(key);
    if (it == m_entries.end())
        return;
    if (status < 200 || status >= 300) {
        m_entries.erase(it);
        return;
    }
    it.value().done   = true;
    it.value().status = status;
    it.value().body   = body;
}

void IdempotencyCache::clear()
{
    QMutexLocker lock(&m_mutex);
    m_entries.clear();
}
