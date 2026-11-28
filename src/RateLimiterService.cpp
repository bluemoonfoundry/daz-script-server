#include "RateLimiterService.h"
#include "ServerConfig.h"

#include <ctime>

namespace {
// Drop timestamps older than the window start.
void pruneBefore(QList<qint64>& timestamps, qint64 windowStart)
{
    QList<qint64>::iterator it = timestamps.begin();
    while (it != timestamps.end()) {
        if (*it < windowStart)
            it = timestamps.erase(it);
        else
            ++it;
    }
}
} // namespace

RateLimiterService::RateLimiterService(int maxRequests, int windowSec)
    : m_bEnabled(false)
    , m_nMax(maxRequests)
    , m_nWindowSec(windowSec)
    , m_cleanupCounter(0)
{}

void RateLimiterService::configure(int maxRequests, int windowSec)
{
    m_nMax       = maxRequests;
    m_nWindowSec = windowSec;
}

bool RateLimiterService::checkRequest(const std::string& clientIP)
{
    if (!m_bEnabled)
        return true;

    QByteArray key(clientIP.c_str(), (int)clientIP.size());
    QMutexLocker lock(&m_mutex);

    qint64 now         = (qint64)time(nullptr);
    qint64 windowStart = now - m_nWindowSec;

    RateLimitInfo& info = m_ipMap[key];

    pruneBefore(info.timestamps, windowStart);

    if (info.timestamps.size() >= m_nMax)
        return false;

    info.timestamps.append(now);

    m_cleanupCounter++;
    if (m_cleanupCounter >= ServerConfig::RATE_LIMIT_CLEANUP_INTERVAL) {
        m_cleanupCounter = 0;
        lock.unlock();
        cleanupStale();
    }

    return true;
}

void RateLimiterService::reset()
{
    QMutexLocker lock(&m_mutex);
    m_ipMap.clear();
    m_cleanupCounter = 0;
}

void RateLimiterService::cleanupStale()
{
    QMutexLocker lock(&m_mutex);

    qint64 now         = (qint64)time(nullptr);
    qint64 windowStart = now - m_nWindowSec;

    QMap<QByteArray, RateLimitInfo>::iterator it = m_ipMap.begin();
    while (it != m_ipMap.end()) {
        RateLimitInfo& info = it.value();
        pruneBefore(info.timestamps, windowStart);

        if (info.timestamps.isEmpty())
            it = m_ipMap.erase(it);
        else
            ++it;
    }
}
