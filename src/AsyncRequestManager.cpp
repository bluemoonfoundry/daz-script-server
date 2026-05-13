#include "AsyncRequestManager.h"
#include "MetricsCollector.h"
#include "JsonBuilder.h"
#include <QtCore/qthread.h>

AsyncRequestManager::AsyncRequestManager(QObject* parent)
    : QObject(parent)
    , m_maxQueueDepth(DEFAULT_MAX_QUEUE_DEPTH)
    , m_maxTrackedRequests(DEFAULT_MAX_TRACKED_REQUESTS)
{}

// ─── HTTP-thread API ──────────────────────────────────────────────────────────

AsyncRequestManager::SubmitResult AsyncRequestManager::submit(
    const QString& scriptText, const QVariantMap& args, const QString& idPrefix)
{
    SubmitResult r;
    r.accepted    = false;
    r.submittedAt = 0;

    {
        QMutexLocker locker(&m_mutex);

        // Enforce resource bounds before accepting the request.
        if (m_queue.size() >= m_maxQueueDepth) {
            r.error = QString("Queue full: %1 requests pending (max %2)")
                      .arg(m_queue.size()).arg(m_maxQueueDepth);
            return r;
        }
        if (m_requests.size() >= m_maxTrackedRequests) {
            r.error = QString("Too many tracked requests: %1 (max %2)")
                      .arg(m_requests.size()).arg(m_maxTrackedRequests);
            return r;
        }

        AsyncRequest req;
        req.id          = MetricsCollector::generateAsyncId(idPrefix);
        req.scriptText  = scriptText;
        req.args        = args;
        req.submittedAt = QDateTime::currentMSecsSinceEpoch();

        m_requests.insert(req.id, req);
        m_queue.enqueue(req.id);

        r.accepted    = true;
        r.id          = req.id;
        r.submittedAt = req.submittedAt;
    }

    // Post wake-up to main thread via QueuedConnection (signal emitted from HTTP thread).
    emit requestEnqueued();
    return r;
}

QPair<int, QString> AsyncRequestManager::getStatusJson(const QString& requestId) const
{
    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(requestId))
        return QPair<int, QString>(404, "{\"success\":false,\"error\":\"Request not found\"}");

    const AsyncRequest& req = m_requests.value(requestId);

    JsonBuilder json;
    json.startObject();
    json.addMember("request_id", req.id);
    json.addMember("status",     statusToString(req.status).c_str());
    json.addMember("progress",   req.progress);

    if (req.status == REQUEST_RUNNING && req.startedAt > 0) {
        qint64 elapsed = QDateTime::currentMSecsSinceEpoch() - req.startedAt;
        json.addMember("elapsed_ms", elapsed);
    }
    if (req.status == REQUEST_QUEUED) {
        int pos = 1;
        QQueue<QString> qCopy = m_queue;
        while (!qCopy.isEmpty()) {
            if (qCopy.dequeue() == requestId) break;
            pos++;
        }
        json.addMember("queue_position", pos);
    }
    json.finishObject();
    return QPair<int, QString>(200, json.toString());
}

QPair<int, QString> AsyncRequestManager::getResultJson(
    const QString& requestId, bool doWait, int timeoutSec)
{
    if (doWait) {
        qint64 deadline = QDateTime::currentMSecsSinceEpoch() + (qint64)timeoutSec * 1000;
        while (QDateTime::currentMSecsSinceEpoch() < deadline) {
            RequestStatus s;
            {
                QMutexLocker locker(&m_mutex);
                if (!m_requests.contains(requestId))
                    return QPair<int, QString>(404, "{\"success\":false,\"error\":\"Request not found\"}");
                s = m_requests.value(requestId).status;
            }
            if (s == REQUEST_COMPLETED || s == REQUEST_FAILED || s == REQUEST_CANCELLED)
                break;
            QThread::msleep(500);
        }
    }

    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(requestId))
        return QPair<int, QString>(404, "{\"success\":false,\"error\":\"Request not found\"}");

    const AsyncRequest& req = m_requests.value(requestId);

    JsonBuilder json;
    json.startObject();
    json.addMember("request_id", req.id);
    json.addMember("status",     statusToString(req.status).c_str());

    if (req.status == REQUEST_COMPLETED) {
        json.addMember("success", true);
        json.addMember("result",  req.scriptResult);
        QVariantList outList;
        foreach (const QString& line, req.outputLines)
            outList << QVariant(line);
        json.addMember("output", QVariant(outList));
        json.addMemberNull("error");
    } else if (req.status == REQUEST_FAILED) {
        json.addMember("success", false);
        json.addMemberNull("result");
        json.addMember("output", QVariant(QVariantList()));
        json.addMember("error",  req.error);
    } else if (req.status == REQUEST_CANCELLED) {
        json.addMember("success", false);
        json.addMemberNull("result");
        json.addMember("output", QVariant(QVariantList()));
        json.addMember("error",  QString("Cancelled"));
    } else {
        json.addMember("progress", req.progress);
        if (req.startedAt > 0) {
            qint64 elapsed = QDateTime::currentMSecsSinceEpoch() - req.startedAt;
            json.addMember("elapsed_ms", elapsed);
        }
    }

    if (req.completedAt > 0 && req.startedAt > 0) {
        json.addMember("duration_ms",  req.completedAt - req.startedAt);
        json.addMember("completed_at",
            QDateTime::fromMSecsSinceEpoch(req.completedAt).toString(Qt::ISODate));
    }
    json.finishObject();
    return QPair<int, QString>(200, json.toString());
}

QPair<int, QString> AsyncRequestManager::cancelJson(
    const QString& requestId, const QString& clientIP)
{
    (void)clientIP;

    RequestStatus statusBefore = REQUEST_QUEUED;
    bool needKillRender = false;
    {
        QMutexLocker locker(&m_mutex);
        if (!m_requests.contains(requestId))
            return QPair<int, QString>(404, "{\"success\":false,\"error\":\"Request not found\"}");

        AsyncRequest& req = m_requests[requestId];
        statusBefore = req.status;

        if (statusBefore == REQUEST_COMPLETED ||
            statusBefore == REQUEST_FAILED    ||
            statusBefore == REQUEST_CANCELLED) {
            return QPair<int, QString>(400, "{\"success\":false,\"error\":\"Request already finished\"}");
        }

        req.cancelRequested = 1;

        if (statusBefore == REQUEST_QUEUED) {
            // Remove from queue immediately; main thread won't pick it up.
            QQueue<QString> newQueue;
            while (!m_queue.isEmpty()) {
                QString id = m_queue.dequeue();
                if (id != requestId) newQueue.enqueue(id);
            }
            m_queue = newQueue;
            req.status      = REQUEST_CANCELLED;
            req.error       = "Cancelled by client";
            req.completedAt = QDateTime::currentMSecsSinceEpoch();
        } else {
            // RUNNING: signal the main thread to call killRender safely.
            needKillRender = true;
        }
    }

    if (needKillRender) {
        // Route the DAZ API call to the main thread via QueuedConnection.
        emit killRenderRequested();
    }

    JsonBuilder json;
    json.startObject();
    json.addMember("request_id",   requestId);
    json.addMember("status",       "cancelled");
    json.addMember("message",      "Cancellation requested");
    json.addMember("cancelled_at", QDateTime::currentDateTime().toString(Qt::ISODate));
    json.finishObject();
    return QPair<int, QString>(200, json.toString());
}

QString AsyncRequestManager::listJson(const QString& statusFilter) const
{
    QMutexLocker locker(&m_mutex);

    QVariantList requestsList;
    int nQueued = 0, nRunning = 0, nCompleted = 0, nFailed = 0, nCancelled = 0;

    for (QMap<QString, AsyncRequest>::const_iterator it = m_requests.constBegin();
         it != m_requests.constEnd(); ++it) {
        const AsyncRequest& req = it.value();
        std::string statusStr = statusToString(req.status);

        if (!statusFilter.isEmpty() && statusStr != statusFilter.toStdString())
            continue;

        QVariantMap entry;
        entry["request_id"]   = req.id;
        entry["status"]       = QString::fromStdString(statusStr);
        entry["progress"]     = req.progress;
        entry["submitted_at"] = QDateTime::fromMSecsSinceEpoch(req.submittedAt)
                                .toString(Qt::ISODate);
        requestsList.append(entry);

        switch (req.status) {
            case REQUEST_QUEUED:    nQueued++;    break;
            case REQUEST_RUNNING:   nRunning++;   break;
            case REQUEST_COMPLETED: nCompleted++; break;
            case REQUEST_FAILED:    nFailed++;    break;
            case REQUEST_CANCELLED: nCancelled++; break;
        }
    }

    JsonBuilder json;
    json.startObject();
    json.addMember("requests",  QVariant(requestsList));
    json.addMember("total",     (int)m_requests.size());
    json.addMember("queued",    nQueued);
    json.addMember("running",   nRunning);
    json.addMember("completed", nCompleted);
    json.addMember("failed",    nFailed);
    json.addMember("cancelled", nCancelled);
    json.finishObject();
    return json.toString();
}

int AsyncRequestManager::getQueueDepth() const
{
    QMutexLocker locker(&m_mutex);
    return m_queue.size();
}

int AsyncRequestManager::getTotalTracked() const
{
    QMutexLocker locker(&m_mutex);
    return m_requests.size();
}

// ─── Main-thread API ──────────────────────────────────────────────────────────

bool AsyncRequestManager::dequeueNext(QString& outId, QString& outScript, QVariantMap& outArgs)
{
    QMutexLocker locker(&m_mutex);
    if (!m_currentId.isEmpty()) return false; // Already running one
    if (m_queue.isEmpty())       return false; // Nothing to do

    QString id = m_queue.dequeue();
    m_currentId = id;

    const AsyncRequest& req = m_requests.value(id);
    outId     = id;
    outScript = req.scriptText;
    outArgs   = req.args;
    return true;
}

void AsyncRequestManager::markRunning(const QString& id)
{
    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(id)) return;
    AsyncRequest& req = m_requests[id];
    req.status    = REQUEST_RUNNING;
    req.startedAt = QDateTime::currentMSecsSinceEpoch();
    req.progress  = 0.0;
}

void AsyncRequestManager::markCompleted(const QString& id, bool executed,
                                        const QVariant& result,
                                        const QStringList& output,
                                        const QString& error,
                                        bool& outWasCancelled)
{
    QMutexLocker locker(&m_mutex);
    outWasCancelled = false;
    if (!m_requests.contains(id)) return;

    AsyncRequest& req    = m_requests[id];
    req.completedAt      = QDateTime::currentMSecsSinceEpoch();
    req.progress         = 1.0;
    req.outputLines      = output;

    if (req.cancelRequested) {
        req.status        = REQUEST_CANCELLED;
        req.error         = "Cancelled by client";
        outWasCancelled   = true;
    } else if (executed) {
        req.status        = REQUEST_COMPLETED;
        req.scriptResult  = result;
        req.scriptExecuted = true;
    } else {
        req.status = REQUEST_FAILED;
        req.error  = error;
    }
}

void AsyncRequestManager::markCancelled(const QString& id, const QString& reason)
{
    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(id)) return;
    AsyncRequest& req = m_requests[id];
    req.status      = REQUEST_CANCELLED;
    req.error       = reason;
    req.completedAt = QDateTime::currentMSecsSinceEpoch();
}

void AsyncRequestManager::clearCurrent()
{
    QMutexLocker locker(&m_mutex);
    m_currentId.clear();
}

bool AsyncRequestManager::isCancelRequested(const QString& id) const
{
    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(id)) return false;
    return m_requests.value(id).cancelRequested != 0;
}

int AsyncRequestManager::cleanupExpired(qint64 ttlMs)
{
    qint64 now = QDateTime::currentMSecsSinceEpoch();

    QStringList toRemove;
    {
        QMutexLocker locker(&m_mutex);
        for (QMap<QString, AsyncRequest>::const_iterator it = m_requests.constBegin();
             it != m_requests.constEnd(); ++it) {
            const AsyncRequest& req = it.value();
            bool terminal = (req.status == REQUEST_COMPLETED ||
                             req.status == REQUEST_FAILED    ||
                             req.status == REQUEST_CANCELLED);
            if (terminal && req.completedAt > 0 && (now - req.completedAt) > ttlMs)
                toRemove.append(it.key());
        }
        foreach (const QString& expired, toRemove)
            m_requests.remove(expired);
    }
    return toRemove.size();
}

void AsyncRequestManager::cancelAllPending(const QString& reason)
{
    QMutexLocker locker(&m_mutex);
    qint64 now = QDateTime::currentMSecsSinceEpoch();
    for (QMap<QString, AsyncRequest>::iterator it = m_requests.begin();
         it != m_requests.end(); ++it) {
        AsyncRequest& req = it.value();
        if (req.status == REQUEST_QUEUED || req.status == REQUEST_RUNNING) {
            req.status      = REQUEST_CANCELLED;
            req.error       = reason;
            req.completedAt = now;
        }
    }
    m_queue.clear();
    m_currentId.clear();
}

// ─── Private helpers ──────────────────────────────────────────────────────────

std::string AsyncRequestManager::statusToString(RequestStatus s) const
{
    switch (s) {
        case REQUEST_QUEUED:    return "queued";
        case REQUEST_RUNNING:   return "running";
        case REQUEST_COMPLETED: return "completed";
        case REQUEST_FAILED:    return "failed";
        case REQUEST_CANCELLED: return "cancelled";
        default:                return "unknown";
    }
}
