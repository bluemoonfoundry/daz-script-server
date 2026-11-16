#include "AsyncRequestManager.h"
#include "JsonStd.h"
#include "MetricsCollector.h"
#include "ErrorResponse.h"
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

void AsyncRequestManager::setServerInstanceId(const QString& id)
{
    QMutexLocker locker(&m_mutex);
    m_serverInstanceId = id;
}

// ─── HTTP-thread API ──────────────────────────────────────────────────────────

AsyncRequestManager::SubmitResult AsyncRequestManager::submit(
    const QString& scriptText, const QString& scriptFile,
    const QString& reportFile, const QVariantMap& args, const QString& idPrefix,
    const QString& correlationId)
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
        req.correlationId    = correlationId;
        req.serverInstanceId = m_serverInstanceId;
        req.scriptText  = scriptText;
        req.scriptFile  = scriptFile;
        req.reportFile  = reportFile;
        req.args        = args;
        if (!reportFile.isEmpty()) {
            req.args.insert("__dssReportFile", reportFile);
            req.progressSource = PROGRESS_REPORT;
        }
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
    const QString& scriptText, const QString& idPrefix, const QString& correlationId,
    const QString& frameReportFile)
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

        // Start the frame report empty so the job never sees another run's
        // events. If it can't be created the render still runs; Studio 4's
        // print marker still reports frames, Studio 6 just reports none.
        bool frameReportReady = false;
        if (!frameReportFile.isEmpty()) {
            QFile report(frameReportFile);
            frameReportReady = report.open(QIODevice::WriteOnly | QIODevice::Truncate);
            report.close();
        }

        AsyncRequest req;
        req.id          = MetricsCollector::generateAsyncId(idPrefix);
        req.requestType = REQUEST_TYPE_RENDER;
        if (!frameReportFile.isEmpty()) {
            req.progressSource = PROGRESS_FRAMES;
            if (frameReportReady) {
                req.reportFile     = frameReportFile;
                req.ownsReportFile = true;
            }
        }
        req.correlationId    = correlationId;
        req.serverInstanceId = m_serverInstanceId;
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
        if (event.contains("frame"))   detail.insert("frame", event.value("frame"));
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

        // Re-declaring a path updates its entry in place, so an artifact_id
        // (the entry's position) never changes once a client has seen it.
        int index = req.outputManifest.size();
        for (int i = 0; i < req.outputManifest.size(); ++i) {
            if (req.outputManifest[i].toMap().value("path").toString() == path) {
                index = i;
                break;
            }
        }
        const QString artifactId = QString::number(index);
        output.insert("artifact_id", artifactId);
        output.insert("url", QString("/artifacts/%1/%2").arg(req.id, artifactId));
        if (index < req.outputManifest.size())
            req.outputManifest[index] = output;
        else
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
        // The file was rewritten (scripts commonly rewrite the whole event
        // list each time). Replay it from the start. Progress is kept rather
        // than cleared: a poll that lands between the truncate and the write
        // would otherwise briefly report no progress at all.
        req.reportOffset = 0;
        req.reportRemainder.clear();
        req.logTail.clear();
        req.logTotal = 0;
        req.outputManifest.clear();
    }
    if (!report.seek(req.reportOffset)) return;
    if (!report.atEnd()) {
        // New events mean the job wrote recently. Use the file's mtime, not
        // the time of this poll, since ingestion happens lazily on request.
        const QDateTime modified = QFileInfo(req.reportFile).lastModified();
        if (modified.isValid())
            touchLocked(req, modified.toMSecsSinceEpoch());
    }

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

// Render jobs don't write a report file; the paths their generated script
// returns (output_path for /render, output_paths for /render/animation) are
// the job's declared outputs, so they become downloadable artifacts too.
void AsyncRequestManager::declareRenderOutputsLocked(AsyncRequest& req, const QVariant& result)
{
    if (result.type() != QVariant::Map) return;
    const QVariantMap map = result.toMap();
    // A failed or aborted render may have left no file (or a partial one).
    if (map.contains("success") && !map.value("success").toBool()) return;

    const QString single = map.value("output_path").toString();
    if (!single.isEmpty()) {
        QVariantMap event;
        event.insert("type", "output");
        event.insert("path", single);
        event.insert("kind", "render");
        applyReportEventLocked(req, event);
    }
    const QVariantList frames = map.value("output_paths").toList();
    for (int i = 0; i < frames.size(); ++i) {
        const QString path = frames[i].toString();
        if (path.isEmpty()) continue;
        QVariantMap event;
        event.insert("type", "output");
        event.insert("path", path);
        event.insert("kind", "frame");
        QVariantMap metadata;
        metadata.insert("index", i);
        event.insert("metadata", metadata);
        applyReportEventLocked(req, event);
    }
}

AsyncRequestManager::ArtifactLookup AsyncRequestManager::findArtifact(
    const std::string& requestId, const std::string& artifactId, QString& outPath)
{
    const QString qid = QString::fromStdString(requestId);
    const QString aid = QString::fromStdString(artifactId);
    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(qid)) return ARTIFACT_JOB_NOT_FOUND;
    AsyncRequest& req = m_requests[qid];
    ingestReportFromWorkerLocked(req);
    for (int i = 0; i < req.outputManifest.size(); ++i) {
        const QVariantMap entry = req.outputManifest[i].toMap();
        if (entry.value("artifact_id").toString() == aid) {
            outPath = entry.value("path").toString();
            return ARTIFACT_FOUND;
        }
    }
    return ARTIFACT_NOT_DECLARED;
}

bool AsyncRequestManager::artifactManifest(const std::string& requestId,
                                           QVariantList& outEntries, QString& outStatus)
{
    const QString qid = QString::fromStdString(requestId);
    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(qid)) return false;
    AsyncRequest& req = m_requests[qid];
    ingestReportFromWorkerLocked(req);
    outEntries = req.outputManifest;
    outStatus  = QString::fromStdString(statusToString(req.status));
    return true;
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
    if (!req.reportFile.isEmpty() && !req.ownsReportFile) {
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
        return {404, ErrorResponse::build(ErrorCode::REQUEST_NOT_FOUND, requestId)};

    AsyncRequest& req = m_requests[qid];
    ingestReportFromWorkerLocked(req);
    std::string status = statusToString(req.status);

    char progBuf[32];
    std::snprintf(progBuf, sizeof(progBuf), "%.15g", req.progress);

    std::string s = "{\"request_id\":\"";
    s += JsonStd::escape(JsonStd::qstrToStd(req.id));
    s += "\",\"status\":\"" + status + "\"";
    s += identityJson(req);
    s += ",\"progress\":" + std::string(progBuf);
    s += activityJson(req);
    s += ",\"observation\":" + observationJson(req);

    s += lifecycleTimesJson(req);

    if (isActive(req.status) && req.startedAt > 0) {
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
                    return {404, ErrorResponse::build(ErrorCode::REQUEST_NOT_FOUND, requestId)};
                s = m_requests.value(qid).status;
            }
            // STALE isn't final, but the server has given up waiting on it,
            // so long-pollers get its success:false answer instead of hanging.
            if (isTerminal(s) || s == REQUEST_STALE)
                break;
            SleepThread::msleep(RESULT_POLL_INTERVAL_MS);
        }
    }

    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(qid))
        return {404, ErrorResponse::build(ErrorCode::REQUEST_NOT_FOUND, requestId)};

    AsyncRequest& mutableReq = m_requests[qid];
    ingestReportFromWorkerLocked(mutableReq);
    const AsyncRequest& observedReq = mutableReq;
    std::string status = statusToString(observedReq.status);

    std::string s = "{\"request_id\":\"";
    s += JsonStd::escape(JsonStd::qstrToStd(observedReq.id));
    s += "\",\"status\":\"" + status + "\"";
    s += identityJson(observedReq);
    s += activityJson(observedReq);

    if (observedReq.status == REQUEST_COMPLETED ||
        observedReq.status == REQUEST_COMPLETED_AFTER_CANCEL_REQUEST ||
        observedReq.status == REQUEST_COMPLETED_AFTER_STALE) {
        s += ",\"success\":true";
        s += ",\"result\":" + JsonStd::variantToJson(observedReq.scriptResult);
        s += ",\"output\":[";
        for (int i = 0; i < observedReq.outputLines.size(); ++i) {
            if (i > 0) s += ",";
            s += "\"" + JsonStd::escape(JsonStd::qstrToStd(observedReq.outputLines[i])) + "\"";
        }
        s += "],\"error\":null";
    } else if (observedReq.status == REQUEST_FAILED || observedReq.status == REQUEST_STALE) {
        s += ",\"success\":false,\"result\":null,\"output\":[],";
        s += ErrorResponse::fields(
            observedReq.status == REQUEST_STALE ? ErrorCode::JOB_STALE : ErrorCode::SCRIPT_ERROR,
            JsonStd::qstrToStd(observedReq.error));
    } else if (observedReq.status == REQUEST_CANCELLED) {
        // A render aborted by killRender() still returns a result object;
        // keep it so the history shows what actually happened.
        s += ",\"success\":false,\"result\":";
        s += observedReq.scriptExecuted ? JsonStd::variantToJson(observedReq.scriptResult) : "null";
        s += ",\"output\":[],";
        s += ErrorResponse::fields(ErrorCode::JOB_CANCELLED);
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

    s += lifecycleTimesJson(observedReq);
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
    return cancelImpl(requestId, false);
}

std::pair<int, std::string> AsyncRequestManager::cancelRenderJson(
    const std::string& requestId, const std::string& clientIP)
{
    (void)clientIP;
    return cancelImpl(requestId, true);
}

// QUEUED requests are removed from the queue and become CANCELLED at once.
// Anything already on the main thread can't be interrupted: the request
// becomes CANCEL_REQUESTED (STALE stays STALE), render jobs get a best-effort
// killRender(), and markCompleted() later records what really happened.
std::pair<int, std::string> AsyncRequestManager::cancelImpl(
    const std::string& requestId, bool renderOnly)
{
    QString qid = QString::fromStdString(requestId);

    bool needKillRender = false;
    RequestStatus statusAfter = REQUEST_QUEUED;
    qint64 cancelAt = 0;
    {
        QMutexLocker locker(&m_mutex);
        if (!m_requests.contains(qid))
            return {404, ErrorResponse::build(ErrorCode::REQUEST_NOT_FOUND, requestId)};

        AsyncRequest& req = m_requests[qid];

        if (renderOnly && req.requestType != REQUEST_TYPE_RENDER)
            return {400, ErrorResponse::build(ErrorCode::NOT_A_RENDER_REQUEST, requestId)};

        if (isTerminal(req.status))
            return {400, ErrorResponse::build(ErrorCode::REQUEST_ALREADY_FINISHED, requestId)};

        const qint64 now = QDateTime::currentMSecsSinceEpoch();
        if (!req.cancelRequested) {
            req.cancelRequested   = 1;
            req.cancelRequestedAt = now;
        }
        cancelAt = req.cancelRequestedAt;

        if (req.status == REQUEST_QUEUED) {
            QQueue<QString> newQueue;
            while (!m_queue.isEmpty()) {
                QString id = m_queue.dequeue();
                if (id != qid) newQueue.enqueue(id);
            }
            m_queue = newQueue;
            req.status      = REQUEST_CANCELLED;
            req.error       = "Cancelled by client before it started";
            req.completedAt = now;
        } else {
            if (req.status == REQUEST_RUNNING)
                req.status = REQUEST_CANCEL_REQUESTED;
            needKillRender = (req.requestType == REQUEST_TYPE_RENDER);
        }
        statusAfter = req.status;
    }

    if (needKillRender) {
        QMetaObject::invokeMethod(m_notifyTarget, "killRenderOnMainThread",
                                  Qt::QueuedConnection);
    }

    std::string s = "{\"request_id\":\"";
    s += JsonStd::escape(requestId);
    s += "\",\"status\":\"" + statusToString(statusAfter) + "\"";
    if (statusAfter == REQUEST_CANCELLED) {
        s += ",\"message\":\"Cancelled before execution started\"";
        s += ",\"cancelled_at\":\"" + JsonStd::msecToIso((long long)cancelAt) + "\"";
    } else {
        s += needKillRender
            ? ",\"message\":\"Cancellation requested; the render is being aborted. Poll the "
              "request for the final outcome.\""
            : ",\"message\":\"Cancellation requested; a running script cannot be interrupted "
              "and will finish on its own. Poll the request for the final outcome.\"";
    }
    s += ",\"cancel_requested_at\":\"" + JsonStd::msecToIso((long long)cancelAt) + "\"";
    s += "}";
    return {200, s};
}

std::string AsyncRequestManager::listJson(const std::string& statusFilter)
{
    QMutexLocker locker(&m_mutex);

    int nQueued = 0, nRunning = 0, nCompleted = 0, nFailed = 0, nCancelled = 0;
    int nCancelRequested = 0, nStale = 0, nCompletedAfterCancel = 0, nCompletedAfterStale = 0;
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
        items += identityJson(req);
        items += ",\"progress\":" + std::string(progBuf);
        items += activityJson(req);
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
            case REQUEST_CANCEL_REQUESTED: ++nCancelRequested; break;
            case REQUEST_STALE:            ++nStale;           break;
            case REQUEST_COMPLETED_AFTER_CANCEL_REQUEST: ++nCompletedAfterCancel; break;
            case REQUEST_COMPLETED_AFTER_STALE:          ++nCompletedAfterStale;  break;
        }
    }

    std::string s = "{\"requests\":[" + items + "]";
    s += ",\"total\":"     + std::to_string((int)m_requests.size());
    s += ",\"queued\":"    + std::to_string(nQueued);
    s += ",\"running\":"   + std::to_string(nRunning);
    s += ",\"completed\":" + std::to_string(nCompleted);
    s += ",\"failed\":"    + std::to_string(nFailed);
    s += ",\"cancelled\":" + std::to_string(nCancelled);
    s += ",\"cancel_requested\":" + std::to_string(nCancelRequested);
    s += ",\"stale\":" + std::to_string(nStale);
    s += ",\"completed_after_cancel_request\":" + std::to_string(nCompletedAfterCancel);
    s += ",\"completed_after_stale\":" + std::to_string(nCompletedAfterStale);
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
    touchLocked(req, req.startedAt);
}

void AsyncRequestManager::updateFrameProgress(const QString& id, int frame, int total)
{
    if (total <= 0 || frame < 1) return;
    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(id)) return;
    AsyncRequest& req = m_requests[id];
    if (req.status != REQUEST_RUNNING) return;
    if (frame > total) frame = total;

    // Same shape as the events the animation script writes to its frame
    // report, so Studio 4 (print marker) and Studio 6 (report) agree.
    QVariantMap detail;
    detail.insert("value", double(frame - 1) / double(total));
    detail.insert("current", frame - 1);
    detail.insert("total", total);
    detail.insert("frame", frame);
    detail.insert("phase", "rendering");
    detail.insert("message", QString("Rendering frame %1 of %2").arg(frame).arg(total));
    req.progress       = detail.value("value").toDouble();
    req.progressDetail = detail;
    touchLocked(req, QDateTime::currentMSecsSinceEpoch());
}

bool AsyncRequestManager::frameProgress(const QString& id, int* frame, int* total)
{
    QMutexLocker locker(&m_mutex);
    if (!m_requests.contains(id)) return false;
    AsyncRequest& req = m_requests[id];
    if (req.progressSource != PROGRESS_FRAMES) return false;
    ingestReportFromWorkerLocked(req);
    const int f = req.progressDetail.value("frame").toInt();
    const int t = req.progressDetail.value("total").toInt();
    if (f < 1 || t < 1) return false;
    if (frame) *frame = f;
    if (total) *total = t;
    return true;
}

void AsyncRequestManager::touchCurrent()
{
    QMutexLocker locker(&m_mutex);
    if (m_currentId.isEmpty() || !m_requests.contains(m_currentId)) return;
    AsyncRequest& req = m_requests[m_currentId];
    if (isActive(req.status))
        touchLocked(req, QDateTime::currentMSecsSinceEpoch());
}

void AsyncRequestManager::touchLocked(AsyncRequest& req, qint64 at)
{
    if (at > req.lastActivityAt)
        req.lastActivityAt = at;
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

    // Only work the main thread still owns is updated. CANCEL_REQUESTED and
    // STALE are deliberately not final: the script has now returned, so record
    // its real outcome rather than discarding it.
    if (!isActive(req.status)) return;
    const bool wasStale = (req.status == REQUEST_STALE);

    req.completedAt    = QDateTime::currentMSecsSinceEpoch();
    touchLocked(req, req.completedAt);
    req.progress       = 1.0;
    if (executed && !req.cancelRequested && !req.progressDetail.isEmpty()) {
        req.progressDetail.insert("value", 1.0);
        // All frames are done; the last frame event said "frame N starting".
        if (req.progressSource == PROGRESS_FRAMES && req.progressDetail.contains("total")) {
            req.progressDetail.insert("current", req.progressDetail.value("total"));
            req.progressDetail.insert("phase", "done");
            req.progressDetail.remove("message");
        }
    }
    req.outputLines    = output;
    for (int i = 0; i < output.size(); ++i) {
        QVariantMap entry;
        entry.insert("level", "info");
        entry.insert("source", "script");
        entry.insert("message", output[i]);
        appendLogLocked(req, entry);
    }

    if (executed) {
        req.scriptResult   = result;
        req.scriptExecuted = true;
        if (req.requestType == REQUEST_TYPE_RENDER)
            declareRenderOutputsLocked(req, result);
    }

    // A render whose script reports success:false after a cancel request was
    // aborted by killRender() -- the only kind of running work that can
    // actually be stopped.
    const bool renderAborted = executed && req.requestType == REQUEST_TYPE_RENDER
        && result.type() == QVariant::Map
        && result.toMap().contains("success") && !result.toMap().value("success").toBool();

    if (req.cancelRequested && renderAborted) {
        req.status      = REQUEST_CANCELLED;
        req.error       = "Cancelled by client";
        outWasCancelled = true;
    } else if (executed) {
        req.status = req.cancelRequested ? REQUEST_COMPLETED_AFTER_CANCEL_REQUEST
                   : wasStale            ? REQUEST_COMPLETED_AFTER_STALE
                                         : REQUEST_COMPLETED;
        req.error.clear();
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
            // STALE entries are purged too: if Daz never unblocks they would
            // otherwise leak, and a late markCompleted() on a purged id no-ops.
            bool terminal = isTerminal(req.status) || req.status == REQUEST_STALE;
            if (terminal && req.completedAt > 0 && (now - req.completedAt) > ttlMs)
                toRemove.append(it.key());
        }
        for (const QString& expired : toRemove) {
            const AsyncRequest& req = m_requests[expired];
            if (req.ownsReportFile && !req.reportFile.isEmpty())
                QFile::remove(req.reportFile);
            m_requests.remove(expired);
        }
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
        if ((req.status == REQUEST_RUNNING || req.status == REQUEST_CANCEL_REQUESTED) &&
            req.startedAt > 0 && (now - req.startedAt) > staleMs) {
            req.status      = REQUEST_STALE;
            req.error       = "Request has been running for longer than expected; "
                               "DAZ Studio's main thread may be blocked behind a dialog "
                               "(e.g. a failed render's error prompt). If the script does "
                               "finish later, this request's status changes to its real "
                               "outcome (e.g. completed_after_stale).";
            req.staleAt     = now;
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
        if (req.status == REQUEST_QUEUED || isActive(req.status)) {
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
        case REQUEST_CANCEL_REQUESTED: return "cancel_requested";
        case REQUEST_STALE:            return "stale";
        case REQUEST_COMPLETED_AFTER_CANCEL_REQUEST: return "completed_after_cancel_request";
        case REQUEST_COMPLETED_AFTER_STALE:          return "completed_after_stale";
        default:                return "unknown";
    }
}

bool AsyncRequestManager::isTerminal(RequestStatus s)
{
    return s == REQUEST_COMPLETED || s == REQUEST_FAILED || s == REQUEST_CANCELLED
        || s == REQUEST_COMPLETED_AFTER_CANCEL_REQUEST || s == REQUEST_COMPLETED_AFTER_STALE;
}

// History fields kept even after the real outcome lands, so a client can see
// that a cancel was requested or the job went stale before it finished.
// ,"correlation_id":"..","server_instance_id":".." -- empty fields omitted.
std::string AsyncRequestManager::identityJson(const AsyncRequest& req)
{
    std::string s;
    if (!req.correlationId.isEmpty())
        s += ",\"correlation_id\":\"" + JsonStd::escape(JsonStd::qstrToStd(req.correlationId)) + "\"";
    if (!req.serverInstanceId.isEmpty())
        s += ",\"server_instance_id\":\"" + JsonStd::escape(JsonStd::qstrToStd(req.serverInstanceId)) + "\"";
    return s;
}

// ,"progress_supported":..,"progress_source":"..","last_activity_at":..|null
// and, while the main thread still owns the job, "idle_ms" since that activity.
std::string AsyncRequestManager::activityJson(const AsyncRequest& req)
{
    // progress_supported means progress can change *while the job runs*.
    // Studio 4 only parses a report after the script returns, so a
    // report-driven job there gets its progress at the end, not live.
    bool supported = false;
    const char* source = "none";
    switch (req.progressSource) {
        case PROGRESS_FRAMES:
            source = "frames";
            supported = true;
            break;
        case PROGRESS_REPORT:
            source = "report";
#if DAZ_SDK_MAJOR_VERSION >= 6
            supported = true;
#endif
            break;
        case PROGRESS_NONE:
            break;
    }
    std::string s = ",\"progress_supported\":";
    s += supported ? "true" : "false";
    s += ",\"progress_source\":\"";
    s += source;
    s += "\",\"last_activity_at\":";
    if (req.lastActivityAt > 0)
        s += "\"" + JsonStd::msecToIso((long long)req.lastActivityAt) + "\"";
    else
        s += "null";
    if (isActive(req.status) && req.lastActivityAt > 0) {
        long long idle = (long long)(QDateTime::currentMSecsSinceEpoch() - req.lastActivityAt);
        if (idle < 0) idle = 0;
        s += ",\"idle_ms\":" + std::to_string(idle);
    }
    return s;
}

std::string AsyncRequestManager::lifecycleTimesJson(const AsyncRequest& req)
{
    std::string s;
    if (req.cancelRequestedAt > 0)
        s += ",\"cancel_requested_at\":\"" + JsonStd::msecToIso((long long)req.cancelRequestedAt) + "\"";
    if (req.staleAt > 0)
        s += ",\"stale_at\":\"" + JsonStd::msecToIso((long long)req.staleAt) + "\"";
    return s;
}
