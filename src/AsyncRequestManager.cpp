#include "AsyncRequestManager.h"
#include "JsonStd.h"
#include "MetricsCollector.h"
#include <QtCore/qdir.h>
#include <QtCore/qfile.h>
#include <QtCore/qfileinfo.h>
#include <QtCore/qobject.h>
#include <QtCore/qthread.h>
#include <QtCore/qmetaobject.h>

// QThread::msleep is protected — access it via a minimal subclass.
namespace {
struct SleepThread : public QThread {
    static void msleep(unsigned long ms) { QThread::msleep(ms); }
};

QString comparablePath(const QString& path)
{
    QFileInfo info(path);
    const QString canonical = info.canonicalFilePath();
    return QDir::cleanPath(canonical.isEmpty() ? info.absoluteFilePath() : canonical);
}
}

AsyncRequestManager::AsyncRequestManager(QObject* notifyTarget)
    : m_notifyTarget(notifyTarget)
    , m_maxQueueDepth(DEFAULT_MAX_QUEUE_DEPTH)
    , m_maxTrackedRequests(DEFAULT_MAX_TRACKED_REQUESTS)
{}

// ─── HTTP-thread API ──────────────────────────────────────────────────────────

AsyncRequestManager::SubmitResult AsyncRequestManager::submit(
    const QString& scriptText, const QString& scriptFile,
    const QString& reportFile, const QVariantMap& args, const QString& idPrefix)
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

        // The report file is an explicit per-job event stream. Own its
        // lifecycle from submission so stale events from an earlier run can
        // never appear in this request's observation record.
        if (!reportFile.isEmpty()) {
            if (!scriptFile.isEmpty() &&
                comparablePath(reportFile).compare(
                    comparablePath(scriptFile), Qt::CaseInsensitive) == 0) {
                r.error = "reportFile must not be the scriptFile";
                return r;
            }
            QFile report(reportFile);
            if (!report.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
                r.error = QString("Cannot initialize reportFile: %1").arg(reportFile);
                return r;
            }
            report.close();
        }

        AsyncRequest req;
        req.id          = MetricsCollector::generateAsyncId(idPrefix);
        req.scriptText  = scriptText;
        req.scriptFile  = scriptFile;
        req.reportFile  = reportFile;
        req.args        = args;
        if (!reportFile.isEmpty())
            req.args.insert("__dssReportFile", reportFile);
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

void AsyncRequestManager::appendLogLocked(AsyncRequest& req, const QVariantMap& logEntry)
{
    req.logTail.append(logEntry);
    ++req.logTotal;
    while (req.logTail.size() > DEFAULT_LOG_TAIL_LINES)
        req.logTail.removeFirst();
}

void AsyncRequestManager::applyReportEventLocked(AsyncRequest& req, const QVariantMap& event)
{
    const QString type = event.value("type").toString().trimmed().toLower();

    if (type == "progress") {
        bool valueOk = false;
        double value = event.value("value").toDouble(&valueOk);
        if (!valueOk) {
            bool currentOk = false, totalOk = false;
            double current = event.value("current").toDouble(&currentOk);
            double total = event.value("total").toDouble(&totalOk);
            if (currentOk && totalOk && total > 0.0) {
                value = current / total;
                valueOk = true;
            }
        }
        if (!valueOk) return;
        if (value < 0.0) value = 0.0;
        if (value > 1.0) value = 1.0;

        QVariantMap detail;
        detail.insert("value", value);
        if (event.contains("current")) detail.insert("current", event.value("current"));
        if (event.contains("total"))   detail.insert("total", event.value("total"));
        if (event.contains("phase"))   detail.insert("phase", event.value("phase"));
        if (event.contains("message")) detail.insert("message", event.value("message"));
        if (event.contains("at"))      detail.insert("at", event.value("at"));
        req.progress = value;
        req.progressDetail = detail;
        return;
    }

    if (type == "log") {
        QString message = event.value("message").toString();
        if (message.isEmpty()) return;
        QVariantMap entry;
        entry.insert("message", message);
        entry.insert("level", event.value("level", "info"));
        entry.insert("source", event.value("source", "script"));
        if (event.contains("at")) entry.insert("at", event.value("at"));
        appendLogLocked(req, entry);
        return;
    }

    if (type == "output") {
        QString path = event.value("path").toString();
        if (path.isEmpty()) return;
        QVariantMap output;
        output.insert("path", path);
        if (event.contains("kind"))     output.insert("kind", event.value("kind"));
        if (event.contains("label"))    output.insert("label", event.value("label"));
        if (event.contains("metadata")) output.insert("metadata", event.value("metadata"));

        for (int i = 0; i < req.outputManifest.size(); ++i) {
            if (req.outputManifest[i].toMap().value("path").toString() == path) {
                req.outputManifest[i] = output;
                return;
            }
        }
        req.outputManifest.append(output);
        return;
    }

    if (type == "manifest") {
        QVariantList outputs = event.value("outputs").toList();
        for (int i = 0; i < outputs.size(); ++i) {
            QVariantMap output = outputs[i].toMap();
            if (!output.isEmpty()) {
                output.insert("type", "output");
                applyReportEventLocked(req, output);
            }
        }
    }
}

void AsyncRequestManager::ingestReportLocked(AsyncRequest& req, bool final)
{
#if DAZ_SDK_MAJOR_VERSION < 6
    // Qt 4's JsonStd::parseObject() constructs a QScriptEngine. This method is
    // therefore main-thread-only on Studio 4; worker-facing callers go through
    // ingestReportFromWorkerLocked(), which deliberately no-ops there.
    Q_ASSERT(!m_notifyTarget || QThread::currentThread() == m_notifyTarget->thread());
#endif
    if (req.reportFile.isEmpty()) return;

    QFile report(req.reportFile);
    if (!report.open(QIODevice::ReadOnly)) return;

    if (report.size() < req.reportOffset) {
        req.reportOffset = 0;
        req.reportRemainder.clear();
        req.progress = 0.0;
        req.progressDetail.clear();
        req.logTail.clear();
        req.logTotal = 0;
        req.outputManifest.clear();
    }
    if (!report.seek(req.reportOffset)) return;

    while (!report.atEnd()) {
        QByteArray chunk = report.read(64 * 1024);
        if (chunk.isEmpty()) break;
        req.reportOffset += chunk.size();
        req.reportRemainder.append(chunk);

        int newline = -1;
        while ((newline = req.reportRemainder.indexOf('\n')) >= 0) {
            QByteArray line = req.reportRemainder.left(newline).trimmed();
            req.reportRemainder.remove(0, newline + 1);
            if (line.isEmpty()) continue;

            QVariantMap event;
            std::string parseError;
            if (JsonStd::parseObject(line, event, parseError)) {
                applyReportEventLocked(req, event);
            } else {
                QVariantMap warning;
                warning.insert("level", "warning");
                warning.insert("source", "server");
                warning.insert("message", "Ignored malformed job report event");
                appendLogLocked(req, warning);
            }
        }

        if (req.reportRemainder.size() > 64 * 1024) {
            req.reportRemainder.clear();
            QVariantMap warning;
            warning.insert("level", "warning");
            warning.insert("source", "server");
            warning.insert("message", "Ignored oversized job report event");
            appendLogLocked(req, warning);
        }
    }

    // JSONL writers should terminate every event with a newline, but accept a
    // complete final object without one once the script can no longer append.
    if (final && !req.reportRemainder.trimmed().isEmpty()) {
        QVariantMap event;
        std::string parseError;
        if (JsonStd::parseObject(req.reportRemainder.trimmed(), event, parseError)) {
            applyReportEventLocked(req, event);
        } else {
            QVariantMap warning;
            warning.insert("level", "warning");
            warning.insert("source", "server");
            warning.insert("message", "Ignored malformed final job report event");
            appendLogLocked(req, warning);
        }
        req.reportRemainder.clear();
    }
}

void AsyncRequestManager::ingestReportFromWorkerLocked(AsyncRequest& req)
{
#if DAZ_SDK_MAJOR_VERSION >= 6
    ingestReportLocked(req);
#else
    // Studio 4 cannot parse report JSON on a raw httplib worker because its
    // JsonStd fallback uses QScriptEngine. markCompleted() performs the final
    // ingestion on Daz's main thread after script execution returns.
    (void)req;
#endif
}

std::string AsyncRequestManager::observationJson(const AsyncRequest& req) const
{
    QVariantMap manifest;
    manifest.insert("count", req.outputManifest.size());
    manifest.insert("outputs", req.outputManifest);

    std::string s = "{\"progress\":";
    s += req.progressDetail.isEmpty()
        ? "null"
        : JsonStd::variantToJson(QVariant(req.progressDetail));
    s += ",\"log_tail\":" + JsonStd::variantToJson(QVariant(req.logTail));
    s += ",\"log_total\":" + std::to_string(req.logTotal);
    s += ",\"log_truncated\":";
    s += (req.logTotal > req.logTail.size()) ? "true" : "false";
    s += ",\"output_manifest\":" + JsonStd::variantToJson(QVariant(manifest));
    if (!req.reportFile.isEmpty()) {
        s += ",\"report_file\":\"";
        s += JsonStd::escape(JsonStd::qstrToStd(req.reportFile));
        s += "\"";
    }
    s += "}";
    return s;
}

std::pair<int, std::string> AsyncRequestManager::getStatusJson(const std::string& requestId)
{
    QString qid = QString::fromStdString(requestId);
    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(qid))
        return {404, "{\"success\":false,\"error\":\"Request not found\"}"};

    AsyncRequest& req = m_requests[qid];
    ingestReportFromWorkerLocked(req);
    std::string status = statusToString(req.status);

    char progBuf[32];
    std::snprintf(progBuf, sizeof(progBuf), "%.15g", req.progress);

    std::string s = "{\"request_id\":\"";
    s += JsonStd::escape(JsonStd::qstrToStd(req.id));
    s += "\",\"status\":\"" + status + "\"";
    s += ",\"progress\":" + std::string(progBuf);
    s += ",\"observation\":" + observationJson(req);

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

    AsyncRequest& mutableReq = m_requests[qid];
    ingestReportFromWorkerLocked(mutableReq);
    const AsyncRequest& observedReq = mutableReq;
    std::string status = statusToString(observedReq.status);

    std::string s = "{\"request_id\":\"";
    s += JsonStd::escape(JsonStd::qstrToStd(observedReq.id));
    s += "\",\"status\":\"" + status + "\"";

    if (observedReq.status == REQUEST_COMPLETED) {
        s += ",\"success\":true";
        s += ",\"result\":" + JsonStd::variantToJson(observedReq.scriptResult);
        s += ",\"output\":[";
        for (int i = 0; i < observedReq.outputLines.size(); ++i) {
            if (i > 0) s += ",";
            s += "\"" + JsonStd::escape(JsonStd::qstrToStd(observedReq.outputLines[i])) + "\"";
        }
        s += "],\"error\":null";
    } else if (observedReq.status == REQUEST_FAILED) {
        s += ",\"success\":false,\"result\":null,\"output\":[]";
        s += ",\"error\":\"" + JsonStd::escape(JsonStd::qstrToStd(observedReq.error)) + "\"";
    } else if (observedReq.status == REQUEST_CANCELLED) {
        s += ",\"success\":false,\"result\":null,\"output\":[]";
        s += ",\"error\":\"Cancelled\"";
    } else {
        char progBuf[32];
        std::snprintf(progBuf, sizeof(progBuf), "%.15g", observedReq.progress);
        s += ",\"progress\":";
        s += progBuf;
        if (observedReq.startedAt > 0) {
            long long elapsed = (long long)(QDateTime::currentMSecsSinceEpoch() - observedReq.startedAt);
            s += ",\"elapsed_ms\":" + std::to_string(elapsed);
        }
    }

    s += ",\"observation\":" + observationJson(observedReq);

    if (observedReq.completedAt > 0 && observedReq.startedAt > 0) {
        s += ",\"duration_ms\":" + std::to_string((long long)(observedReq.completedAt - observedReq.startedAt));
        s += ",\"completed_at\":\"" + JsonStd::msecToIso((long long)observedReq.completedAt) + "\"";
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

std::string AsyncRequestManager::listJson(const std::string& statusFilter)
{
    QMutexLocker locker(&m_mutex);

    int nQueued = 0, nRunning = 0, nCompleted = 0, nFailed = 0, nCancelled = 0;
    std::string items;

    for (QMap<QString, AsyncRequest>::iterator it = m_requests.begin();
         it != m_requests.end(); ++it) {
        AsyncRequest& req = it.value();
        ingestReportFromWorkerLocked(req);
        std::string statusStr = statusToString(req.status);

        if (!statusFilter.empty() && statusStr != statusFilter)
            continue;

        char progBuf[32];
        std::snprintf(progBuf, sizeof(progBuf), "%.15g", req.progress);

        if (!items.empty()) items += ",";
        items += "{\"request_id\":\"" + JsonStd::escape(JsonStd::qstrToStd(req.id)) + "\"";
        items += ",\"status\":\"" + statusStr + "\"";
        items += ",\"progress\":" + std::string(progBuf);
        items += ",\"observation_summary\":{";
        items += "\"log_total\":" + std::to_string(req.logTotal);
        items += ",\"log_truncated\":";
        items += (req.logTotal > req.logTail.size()) ? "true" : "false";
        items += ",\"output_count\":" + std::to_string(req.outputManifest.size());
        items += ",\"progress\":";
        items += req.progressDetail.isEmpty()
            ? "null"
            : JsonStd::variantToJson(QVariant(req.progressDetail));
        items += "}";
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

bool AsyncRequestManager::dequeueNext(QString& outId, QString& outScript,
                                      QString& outScriptFile, QVariantMap& outArgs)
{
    QMutexLocker locker(&m_mutex);
    if (!m_currentId.isEmpty()) return false;
    if (m_queue.isEmpty())       return false;

    QString id = m_queue.dequeue();
    m_currentId = id;

    const AsyncRequest& req = m_requests.value(id);
    outId     = id;
    outScript = req.scriptText;
    outScriptFile = req.scriptFile;
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

void AsyncRequestManager::updateProgress(const QString& id, double progress)
{
    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(id)) return;
    AsyncRequest& req = m_requests[id];
    if (req.status != REQUEST_RUNNING) return;
    req.progress = progress;
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

    // This is the main-thread ingestion path for every SDK. It is also the
    // only report parser used by Studio 4, where JsonStd relies on the
    // thread-affine QScriptEngine. Parse before the terminal-state guard so a
    // script that returned after client cancellation or stale-job failure can
    // still publish its final observation safely.
    ingestReportLocked(req, true);

    // If failStaleRunning() already timed this request out (RUNNING -> FAILED)
    // while the underlying DazScript call was blocked, that terminal state
    // sticks -- a late, real completion must not flip it back to
    // COMPLETED/CANCELLED after a client may have already acted on "failed".
    if (req.status != REQUEST_RUNNING) return;

    req.completedAt    = QDateTime::currentMSecsSinceEpoch();
    req.progress       = 1.0;
    if (executed && !req.cancelRequested && !req.progressDetail.isEmpty())
        req.progressDetail.insert("value", 1.0);
    req.outputLines    = output;
    for (int i = 0; i < output.size(); ++i) {
        QVariantMap entry;
        entry.insert("level", "info");
        entry.insert("source", "script");
        entry.insert("message", output[i]);
        appendLogLocked(req, entry);
    }

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
