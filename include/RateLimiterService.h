#pragma once
#include <string>
#include <QtCore/qbytearray.h>
#include <QtCore/qmap.h>
#include <QtCore/qlist.h>
#include <QtCore/qmutex.h>

// Per-IP sliding-window rate limiter. Thread-safe.
class RateLimiterService {
public:
    explicit RateLimiterService(int maxRequests = 60, int windowSec = 60);

    void configure(int maxRequests, int windowSec);
    void setEnabled(bool enabled) { m_bEnabled = enabled; }
    bool isEnabled() const        { return m_bEnabled; }

    // Returns true if the request is allowed, false if the IP is over limit.
    // Safe to call from any thread — no Qt string allocation/deallocation.
    bool checkRequest(const std::string& clientIP);

    // Clears all per-IP tracking (call on server stop).
    void reset();

private:
    struct RateLimitInfo {
        QList<qint64> timestamps;
    };

    void cleanupStale();

    bool  m_bEnabled;
    int   m_nMax;
    int   m_nWindowSec;

    QMap<QByteArray, RateLimitInfo> m_ipMap;
    QMutex  m_mutex;
    int     m_cleanupCounter;
};
