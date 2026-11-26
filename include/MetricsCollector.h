#pragma once
#include <QtCore/qdatetime.h>
#include <QtCore/qmutex.h>
#include <QtCore/qstring.h>
#include <string>

// Thread-safe metrics counter. recordRequest/recordAuthFailure may be called
// from the main thread or from HTTP threads.
class MetricsCollector {
public:
    static const int REQUEST_ID_LENGTH = 8;  // Characters taken from UUID for request/async IDs
    static const int SAVE_INTERVAL     = 10; // Persist metrics to QSettings every N requests

    MetricsCollector();

    void recordRequest(bool success);
    void recordAuthFailure();

    // Records how long a synchronous /execute request waited between the
    // HTTP thread posting its MainThreadCall and
    // handleExecuteRequest() starting to run on the main thread.
    void recordMainThreadWait(qint64 waitMs);

    qint64 getAvgMainThreadWaitMs() const;
    qint64 getMaxMainThreadWaitMs() const;

    // GET /metrics body. std::string only: called from httplib worker threads
    // (no QString temporaries freed across the Studio 4 CRT boundary).
    std::string toJson(int activeRequests) const;

    void saveToSettings();
    void loadFromSettings();

    static QString generateRequestId();
    static QString generateAsyncId(const QString& type);

    // Thread-safe accessors
    int     getTotalRequests()      const;
    int     getSuccessfulRequests() const;
    int     getFailedRequests()     const;
    int     getAuthFailures()       const;
    qint64  getUptimeSeconds()      const;

private:
    int       m_nTotal;
    int       m_nSuccessful;
    int       m_nFailed;
    int       m_nAuthFailures;
    QDateTime m_startTime;
    qint64    m_nMainThreadWaitSamples;
    qint64    m_nMainThreadWaitSumMs;
    qint64    m_nMainThreadWaitMaxMs;
    mutable QMutex m_mutex;
};
