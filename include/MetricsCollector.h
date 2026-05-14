#pragma once
#include <QtCore/qdatetime.h>
#include <QtCore/qmutex.h>
#include <QtCore/qstring.h>

// Thread-safe metrics counter. recordRequest/recordAuthFailure may be called
// from the main thread or from HTTP threads (via BlockingQueuedConnection).
class MetricsCollector {
public:
    static const int REQUEST_ID_LENGTH = 8;  // Characters taken from UUID for request/async IDs
    static const int SAVE_INTERVAL     = 10; // Persist metrics to QSettings every N requests

    MetricsCollector();

    void recordRequest(bool success);
    void recordAuthFailure();

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
    QDateTime getStartTime()        const;

private:
    int       m_nTotal;
    int       m_nSuccessful;
    int       m_nFailed;
    int       m_nAuthFailures;
    QDateTime m_startTime;
    mutable QMutex m_mutex;
};
