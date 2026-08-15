#include "AsyncRequestManager.h"
#include "JsonStd.h"
#include "MetricsCollector.h"
#include <QtCore/qthread.h>
#include <QtCore/qmetaobject.h>

// QThread::msleep is protected — access it via a minimal subclass.
namespace {
struct SleepThread : public QThread {
    static void msleep(unsigned long ms) { QThread::msleep(ms); }
};
}

AsyncRequestManager::AsyncRequestManager(QObject* notifyTarget)
    : m_notifyTarget(notifyTarget)
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

    // Post wake-up to main thread via QueuedConnection (called from HTTP thread).
    QMetaObject::invokeMethod(m_notifyTarget, "processNextAsyncRequest",
                              Qt::QueuedConnection);
    return r;
}

AsyncRequestManager::SubmitResult AsyncRequestManager::submitRender(
    const QString& scriptText, const QString& idPrefix)
{
    SubmitResult r;
    r.accepted    = false;
    r.submittedAt = 0;

    {
        QMutexLocker locker(&m_mutex);

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
        req.requestType = REQUEST_TYPE_RENDER;
        req.scriptText  = scriptText;
        req.submittedAt = QDateTime::currentMSecsSinceEpoch();

        m_requests.insert(req.id, req);
        m_queue.enqueue(req.id);

        r.accepted    = true;
        r.id          = req.id;
        r.submittedAt = req.submittedAt;
    }

    QMetaObject::invokeMethod(m_notifyTarget, "processNextAsyncRequest",
                              Qt::QueuedConnection);
    return r;
}

std::pair<int, std::string> AsyncRequestManager::getStatusJson(const std::string& requestId) const
{
    QString qid = QString::fromStdString(requestId);
    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(qid))
        return {404, "{\"success\":false,\"error\":\"Request not found\"}"};

    const AsyncRequest& req = m_requests.value(qid);
    std::string status = statusToString(req.status);

    char progBuf[32];
    std::snprintf(progBuf, sizeof(progBuf), "%.15g", req.progress);

    std::string s = "{\"request_id\":\"";
    s += JsonStd::escape(JsonStd::qstrToStd(req.id));
    s += "\",\"status\":\"" + status + "\"";
    s += ",\"progress\":" + std::string(progBuf);

    if (req.status == REQUEST_RUNNING && req.startedAt > 0) {
        long long elapsed = (long long)(QDateTime::currentMSecsSinceEpoch() - req.startedAt);
        s += ",\"elapsed_ms\":" + std::to_string(elapsed);
    }
    if (req.status == REQUEST_QUEUED) {
        int pos = 1;
        QQueue<QString> qCopy = m_queue;
        while (!qCopy.isEmpty()) {
            if (qCopy.dequeue() == qid) break;
            ++pos;
        }
        s += ",\"queue_position\":" + std::to_string(pos);
    }
    s += "}";
    return {200, s};
}

std::pair<int, std::string> AsyncRequestManager::getResultJson(
    const std::string& requestId, bool doWait, int timeoutSec)
{
    QString qid = QString::fromStdString(requestId);

    if (doWait) {
        qint64 deadline = QDateTime::currentMSecsSinceEpoch() + (qint64)timeoutSec * 1000;
        while (QDateTime::currentMSecsSinceEpoch() < deadline) {
            RequestStatus s;
            {
                QMutexLocker locker(&m_mutex);
                if (!m_requests.contains(qid))
                    return {404, "{\"success\":false,\"error\":\"Request not found\"}"};
                s = m_requests.value(qid).status;
            }
            if (s == REQUEST_COMPLETED || s == REQUEST_FAILED || s == REQUEST_CANCELLED)
                break;
            SleepThread::msleep(RESULT_POLL_INTERVAL_MS);
        }
    }

    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(qid))
        return {404, "{\"success\":false,\"error\":\"Request not found\"}"};

    const AsyncRequest& req = m_requests.value(qid);
    std::string status = statusToString(req.status);

    std::string s = "{\"request_id\":\"";
    s += JsonStd::escape(JsonStd::qstrToStd(req.id));
    s += "\",\"status\":\"" + status + "\"";

    if (req.status == REQUEST_COMPLETED) {
        s += ",\"success\":true";
        s += ",\"result\":" + JsonStd::variantToJson(req.scriptResult);
        s += ",\"output\":[";
        for (int i = 0; i < req.outputLines.size(); ++i) {
            if (i > 0) s += ",";
            s += "\"" + JsonStd::escape(JsonStd::qstrToStd(req.outputLines[i])) + "\"";
        }
        s += "],\"error\":null";
    } else if (req.status == REQUEST_FAILED) {
        s += ",\"success\":false,\"result\":null,\"output\":[]";
        s += ",\"error\":\"" + JsonStd::escape(JsonStd::qstrToStd(req.error)) + "\"";
    } else if (req.status == REQUEST_CANCELLED) {
        s += ",\"success\":false,\"result\":null,\"output\":[]";
        s += ",\"error\":\"Cancelled\"";
    } else {
        char progBuf[32];
        std::snprintf(progBuf, sizeof(progBuf), "%.15g", req.progress);
        s += ",\"progress\":";
        s += progBuf;
        if (req.startedAt > 0) {
            long long elapsed = (long long)(QDateTime::currentMSecsSinceEpoch() - req.startedAt);
            s += ",\"elapsed_ms\":" + std::to_string(elapsed);
        }
    }

    if (req.completedAt > 0 && req.startedAt > 0) {
        s += ",\"duration_ms\":" + std::to_string((long long)(req.completedAt - req.startedAt));
        s += ",\"completed_at\":\"" + JsonStd::msecToIso((long long)req.completedAt) + "\"";
    }
    s += "}";
    return {200, s};
}

std::pair<int, std::string> AsyncRequestManager::cancelJson(
    const std::string& requestId, const std::string& clientIP)
{
    (void)clientIP;
    QString qid = QString::fromStdString(requestId);

    RequestStatus statusBefore = REQUEST_QUEUED;
    bool needKillRender = false;
    {
        QMutexLocker locker(&m_mutex);
        if (!m_requests.contains(qid))
            return {404, "{\"success\":false,\"error\":\"Request not found\"}"};

        AsyncRequest& req = m_requests[qid];
        statusBefore = req.status;

        if (statusBefore == REQUEST_COMPLETED ||
            statusBefore == REQUEST_FAILED    ||
            statusBefore == REQUEST_CANCELLED) {
            return {400, "{\"success\":false,\"error\":\"Request already finished\"}"};
        }

        req.cancelRequested = 1;

        if (statusBefore == REQUEST_QUEUED) {
            QQueue<QString> newQueue;
            while (!m_queue.isEmpty()) {
                QString id = m_queue.dequeue();
                if (id != qid) newQueue.enqueue(id);
            }
            m_queue = newQueue;
        } else {
            needKillRender = (req.requestType == REQUEST_TYPE_RENDER);
        }

        // Mark cancelled immediately regardless of whether we can actually
        // interrupt a RUNNING request's underlying operation (killRender()
        // may find nothing to kill, e.g. a renderer already wedged behind a
        // modal). The tracker's status must match the "cancelled" response
        // we're about to return, not silently stay "running" forever. If the
        // underlying call does complete later, markCompleted() no-ops for a
        // request already in a terminal state (see markCompleted).
        req.status      = REQUEST_CANCELLED;
        req.error       = "Cancelled by client";
        req.completedAt = QDateTime::currentMSecsSinceEpoch();
    }

    if (needKillRender) {
        QMetaObject::invokeMethod(m_notifyTarget, "killRenderOnMainThread",
                                  Qt::QueuedConnection);
    }

    long long nowMs = (long long)QDateTime::currentMSecsSinceEpoch();
    std::string s = "{\"request_id\":\"";
    s += JsonStd::escape(requestId);
    s += "\",\"status\":\"cancelled\"";
    s += ",\"message\":\"Cancellation requested\"";
    s += ",\"cancelled_at\":\"" + JsonStd::msecToIso(nowMs) + "\"";
    s += "}";
    return {200, s};
}

std::pair<int, std::string> AsyncRequestManager::cancelRenderJson(
    const std::string& requestId, const std::string& clientIP)
{
    (void)clientIP;
    QString qid = QString::fromStdString(requestId);

    bool needKillRender = false;
    {
        QMutexLocker locker(&m_mutex);
        if (!m_requests.contains(qid))
            return {404, "{\"success\":false,\"error\":\"Request not found\"}"};

        AsyncRequest& req = m_requests[qid];

        if (req.requestType != REQUEST_TYPE_RENDER)
            return {400, "{\"success\":false,\"error\":\"Not a render request\"}"};

        RequestStatus statusBefore = req.status;

        if (statusBefore == REQUEST_COMPLETED ||
            statusBefore == REQUEST_FAILED    ||
            statusBefore == REQUEST_CANCELLED) {
            return {400, "{\"success\":false,\"error\":\"Request already finished\"}"};
        }

        req.cancelRequested = 1;

        if (statusBefore == REQUEST_QUEUED) {
            QQueue<QString> newQueue;
            while (!m_queue.isEmpty()) {
                QString id = m_queue.dequeue();
                if (id != qid) newQueue.enqueue(id);
            }
            m_queue = newQueue;
        } else {
            needKillRender = true;
        }

        // See the matching comment in cancelJson(): mark cancelled
        // immediately even though killRender() is best-effort and may find
        // nothing to kill (renderer already wedged behind a modal), so the
        // tracker's status can't be left stuck at "running" forever while
        // the HTTP response already claims "cancelled".
        req.status      = REQUEST_CANCELLED;
        req.error       = "Cancelled by client";
        req.completedAt = QDateTime::currentMSecsSinceEpoch();
    }

    if (needKillRender) {
        QMetaObject::invokeMethod(m_notifyTarget, "killRenderOnMainThread",
                                  Qt::QueuedConnection);
    }

    long long nowMs = (long long)QDateTime::currentMSecsSinceEpoch();
    std::string s = "{\"request_id\":\"";
    s += JsonStd::escape(requestId);
    s += "\",\"status\":\"cancelled\"";
    s += ",\"message\":\"Cancellation requested\"";
    s += ",\"cancelled_at\":\"" + JsonStd::msecToIso(nowMs) + "\"";
    s += "}";
    return {200, s};
}

std::string AsyncRequestManager::listJson(const std::string& statusFilter) const
{
    QMutexLocker locker(&m_mutex);

    int nQueued = 0, nRunning = 0, nCompleted = 0, nFailed = 0, nCancelled = 0;
    std::string items;

    for (QMap<QString, AsyncRequest>::const_iterator it = m_requests.constBegin();
         it != m_requests.constEnd(); ++it) {
        const AsyncRequest& req = it.value();
        std::string statusStr = statusToString(req.status);

        if (!statusFilter.empty() && statusStr != statusFilter)
            continue;

        char progBuf[32];
        std::snprintf(progBuf, sizeof(progBuf), "%.15g", req.progress);

        if (!items.empty()) items += ",";
        items += "{\"request_id\":\"" + JsonStd::escape(JsonStd::qstrToStd(req.id)) + "\"";
        items += ",\"status\":\"" + statusStr + "\"";
        items += ",\"progress\":" + std::string(progBuf);
        items += ",\"submitted_at\":\"" + JsonStd::msecToIso((long long)req.submittedAt) + "\"}";

        switch (req.status) {
            case REQUEST_QUEUED:    ++nQueued;    break;
            case REQUEST_RUNNING:   ++nRunning;   break;
            case REQUEST_COMPLETED: ++nCompleted; break;
            case REQUEST_FAILED:    ++nFailed;    break;
            case REQUEST_CANCELLED: ++nCancelled; break;
        }
    }

    std::string s = "{\"requests\":[" + items + "]";
    s += ",\"total\":"     + std::to_string((int)m_requests.size());
    s += ",\"queued\":"    + std::to_string(nQueued);
    s += ",\"running\":"   + std::to_string(nRunning);
    s += ",\"completed\":" + std::to_string(nCompleted);
    s += ",\"failed\":"    + std::to_string(nFailed);
    s += ",\"cancelled\":" + std::to_string(nCancelled);
    s += "}";
    return s;
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
    if (!m_currentId.isEmpty()) return false;
    if (m_queue.isEmpty())       return false;

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

    AsyncRequest& req  = m_requests[id];

    // If failStaleRunning() already timed this request out (RUNNING -> FAILED)
    // while the underlying DazScript call was blocked, that terminal state
    // sticks -- a late, real completion must not flip it back to
    // COMPLETED/CANCELLED after a client may have already acted on "failed".
    if (req.status != REQUEST_RUNNING) return;

    req.completedAt    = QDateTime::currentMSecsSinceEpoch();
    req.progress       = 1.0;
    req.outputLines    = output;

    if (req.cancelRequested) {
        req.status       = REQUEST_CANCELLED;
        req.error        = "Cancelled by client";
        outWasCancelled  = true;
    } else if (executed) {
        req.status         = REQUEST_COMPLETED;
        req.scriptResult   = result;
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
        for (const QString& expired : toRemove)
            m_requests.remove(expired);
    }
    return toRemove.size();
}

int AsyncRequestManager::failStaleRunning(qint64 staleMs)
{
    qint64 now = QDateTime::currentMSecsSinceEpoch();
    int failedCount = 0;

    QMutexLocker locker(&m_mutex);
    for (QMap<QString, AsyncRequest>::iterator it = m_requests.begin();
         it != m_requests.end(); ++it) {
        AsyncRequest& req = it.value();
        if (req.status == REQUEST_RUNNING && req.startedAt > 0 &&
            (now - req.startedAt) > staleMs) {
            req.status      = REQUEST_FAILED;
            req.error       = "Request timed out after running for longer than expected; "
                               "DAZ Studio's main thread may be blocked behind a dialog "
                               "(e.g. a failed render's error prompt). This request's script "
                               "may still complete in the background, but its result will no "
                               "longer be tracked -- check DAZ Studio directly.";
            req.completedAt = now;
            ++failedCount;
        }
    }
    return failedCount;
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
