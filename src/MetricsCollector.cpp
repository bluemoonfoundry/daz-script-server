#include "MetricsCollector.h"

#include <QtCore/qsettings.h>
#include <QtCore/quuid.h>

MetricsCollector::MetricsCollector()
    : m_nTotal(0)
    , m_nSuccessful(0)
    , m_nFailed(0)
    , m_nAuthFailures(0)
    , m_startTime(QDateTime::currentDateTime())
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
        shouldSave = (m_nTotal % 10 == 0);
    }
    if (shouldSave)
        saveToSettings();
}

void MetricsCollector::recordAuthFailure()
{
    QMutexLocker lock(&m_mutex);
    m_nAuthFailures++;
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
    return uuid.toString().mid(1, 8);
}

// static
QString MetricsCollector::generateAsyncId(const QString& type)
{
    QString uuid = QUuid::createUuid().toString();
    return type + "-" + uuid.mid(1, 8);
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

QDateTime MetricsCollector::getStartTime() const
{
    QMutexLocker lock(&m_mutex);
    return m_startTime;
}
