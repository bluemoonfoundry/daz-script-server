#include "MetricsCollector.h"
#include <cstdio>

#include <QtCore/qsettings.h>
#include <QtCore/quuid.h>

MetricsCollector::MetricsCollector()
    : m_nTotal(0)
    , m_nSuccessful(0)
    , m_nFailed(0)
    , m_nAuthFailures(0)
    , m_startTime(QDateTime::currentDateTime())
    , m_nMainThreadWaitSamples(0)
    , m_nMainThreadWaitSumMs(0)
    , m_nMainThreadWaitMaxMs(0)
{}

void MetricsCollector::recordRequest(bool success)
{
    bool shouldSave;
    {
        QMutexLocker lock(&m_mutex);
        m_nTotal++;
        if (success)
            m_nSuccessful++;
        else
            m_nFailed++;
        shouldSave = (m_nTotal % SAVE_INTERVAL == 0);
    }
    if (shouldSave)
        saveToSettings();
}

void MetricsCollector::recordAuthFailure()
{
    QMutexLocker lock(&m_mutex);
    m_nAuthFailures++;
}

void MetricsCollector::recordMainThreadWait(qint64 waitMs)
{
    QMutexLocker lock(&m_mutex);
    m_nMainThreadWaitSamples++;
    m_nMainThreadWaitSumMs += waitMs;
    if (waitMs > m_nMainThreadWaitMaxMs) m_nMainThreadWaitMaxMs = waitMs;
}

qint64 MetricsCollector::getAvgMainThreadWaitMs() const
{
    QMutexLocker lock(&m_mutex);
    return m_nMainThreadWaitSamples > 0 ? m_nMainThreadWaitSumMs / m_nMainThreadWaitSamples : 0;
}

qint64 MetricsCollector::getMaxMainThreadWaitMs() const
{
    QMutexLocker lock(&m_mutex);
    return m_nMainThreadWaitMaxMs;
}

void MetricsCollector::saveToSettings()
{
    int total, successful, failed, authFail;
    {
        QMutexLocker lock(&m_mutex);
        total      = m_nTotal;
        successful = m_nSuccessful;
        failed     = m_nFailed;
        authFail   = m_nAuthFailures;
    }
    QSettings settings("DAZ 3D", "DazScriptServer");
    settings.setValue("metrics/totalRequests",      total);
    settings.setValue("metrics/successfulRequests", successful);
    settings.setValue("metrics/failedRequests",     failed);
    settings.setValue("metrics/authFailures",       authFail);
}

void MetricsCollector::loadFromSettings()
{
    QSettings settings("DAZ 3D", "DazScriptServer");
    QMutexLocker lock(&m_mutex);
    m_nTotal        = settings.value("metrics/totalRequests",      0).toInt();
    m_nSuccessful   = settings.value("metrics/successfulRequests", 0).toInt();
    m_nFailed       = settings.value("metrics/failedRequests",     0).toInt();
    m_nAuthFailures = settings.value("metrics/authFailures",       0).toInt();
}

// static
QString MetricsCollector::generateRequestId()
{
    QUuid uuid = QUuid::createUuid();
    return uuid.toString().mid(1, REQUEST_ID_LENGTH);
}

// static
QString MetricsCollector::generateAsyncId(const QString& type)
{
    QString uuid = QUuid::createUuid().toString();
    return type + "-" + uuid.mid(1, REQUEST_ID_LENGTH);
}

int MetricsCollector::getTotalRequests() const
{
    QMutexLocker lock(&m_mutex);
    return m_nTotal;
}

int MetricsCollector::getSuccessfulRequests() const
{
    QMutexLocker lock(&m_mutex);
    return m_nSuccessful;
}

int MetricsCollector::getFailedRequests() const
{
    QMutexLocker lock(&m_mutex);
    return m_nFailed;
}

int MetricsCollector::getAuthFailures() const
{
    QMutexLocker lock(&m_mutex);
    return m_nAuthFailures;
}

qint64 MetricsCollector::getUptimeSeconds() const
{
    QMutexLocker lock(&m_mutex);
    return m_startTime.secsTo(QDateTime::currentDateTime());
}

std::string MetricsCollector::toJson(int activeRequests) const
{
	// Build with std::string only — called from httplib worker threads where Qt string ops are unsafe.
	int total      = getTotalRequests();
	int successful = getSuccessfulRequests();
	int failed     = getFailedRequests();
	int authFail   = getAuthFailures();
	int active     = activeRequests;
	long long uptime = (long long)getUptimeSeconds();
	double rate    = total > 0 ? (double)successful / total * 100.0 : 0.0;

	char rateBuf[32];
	std::snprintf(rateBuf, sizeof(rateBuf), "%.15g", rate);

	std::string s = "{\"total_requests\":";
	s += std::to_string(total);
	s += ",\"successful_requests\":";
	s += std::to_string(successful);
	s += ",\"failed_requests\":";
	s += std::to_string(failed);
	s += ",\"auth_failures\":";
	s += std::to_string(authFail);
	s += ",\"active_requests\":";
	s += std::to_string(active);
	s += ",\"uptime_seconds\":";
	s += std::to_string(uptime);
	s += ",\"success_rate_percent\":";
	s += rateBuf;
	s += ",\"avg_main_thread_wait_ms\":";
	s += std::to_string((long long)getAvgMainThreadWaitMs());
	s += ",\"max_main_thread_wait_ms\":";
	s += std::to_string((long long)getMaxMainThreadWaitMs());
	s += "}";
	return s;
}
