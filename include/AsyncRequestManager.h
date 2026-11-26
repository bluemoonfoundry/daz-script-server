#pragma once
#include <QtCore/qstring.h>
#include "ServerConfig.h"
#include <QtCore/qmap.h>
#include <QtCore/qqueue.h>
#include <QtCore/qmutex.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qpair.h>
#include <QtCore/qvariant.h>
#include <QtCore/qstringlist.h>
#include <QtCore/qvector.h>
#include <QtCore/qbytearray.h>
#include <string>
#include <functional>
#include <utility>

// Forward declaration — AsyncRequestManager calls back into the pane via
// QMetaObject::invokeMethod rather than using Qt signals, which avoids the
// Q_OBJECT / AUTOMOC dependency and the QObject include chain issue with the
// DAZ Qt4 SDK headers.
class QObject;

// ─── AsyncRequestManager ─────────────────────────────────────────────────────
//
// THREADING MODEL:
//   HTTP threads : submit(), getStatusJson(), getResultJson(), cancelJson(),
//                  listJson() — all acquire m_mutex internally.
//   Main thread  : dequeueNext(), markRunning(), markCompleted(),
//                  markCancelled(), clearCurrent(), cleanupExpired()
//                  — also acquire m_mutex; called only from the Qt main thread.
//
// CROSS-THREAD NOTIFICATIONS (via QMetaObject::invokeMethod, QueuedConnection):
//   m_notifyTarget / "processNextAsyncRequest"  — wakeup on each submit.
//   m_notifyTarget / "killRenderOnMainThread"   — routes DAZ killRender() to
//                  main thread instead of calling it from an HTTP thread.

class AsyncRequestManager {
public:
    static const int DEFAULT_MAX_QUEUE_DEPTH      = ServerConfig::ASYNC_MAX_QUEUE_DEPTH;
    static const int DEFAULT_MAX_TRACKED_REQUESTS = ServerConfig::ASYNC_MAX_TRACKED_REQUESTS;
    static const int DEFAULT_LOG_TAIL_LINES       = ServerConfig::ASYNC_LOG_TAIL_LINES;
    static const int RESULT_POLL_INTERVAL_MS      = ServerConfig::ASYNC_RESULT_POLL_INTERVAL_MS;

    // notifyTarget must be a DzScriptServerPane* (QObject subclass).
    // Stored as QObject* to avoid the DAZ header dependency here.
    explicit AsyncRequestManager(QObject* notifyTarget);

    // Limits (fixed at the DEFAULT_* values above).
    int  maxQueueDepth() const        { return m_maxQueueDepth; }
    int  maxTrackedRequests() const   { return m_maxTrackedRequests; }

    // Identity of the current server run, stamped onto every job submitted
    // from now on (jobs from an earlier run keep theirs). Call on server start.
    void setServerInstanceId(const QString& id);

    // ── HTTP-thread API ────────────────────────────────────────────────────

    struct SubmitResult {
        bool    accepted;
        QString id;
        qint64  submittedAt;
        QString error; // set only when !accepted
    };

    enum RequestType { REQUEST_TYPE_SCRIPT, REQUEST_TYPE_RENDER };

    // Enqueue a new async request. Returns SubmitResult::accepted=false when
    // the queue is at capacity or too many requests are tracked.
    // correlationId is the client's X-Correlation-Id (or a generated one);
    // it is echoed in every status/result/list record for this job.
    SubmitResult        submit(const QString& scriptText, const QString& scriptFile,
                               const QString& reportFile, const QVariantMap& args,
                               const QString& idPrefix, const QString& correlationId);

    // Enqueue a render job. Same as submit() but tags the request as
    // REQUEST_TYPE_RENDER so cancel dispatch calls killRender() correctly.
    // frameReportFile is non-empty for animation renders: a server-owned
    // JSONL file the generated script writes one progress event per frame
    // to (Studio 6 reads it live; see onMessagePosted for Studio 4). The
    // manager truncates it on submit and deletes it when the job expires.
    SubmitResult        submitRender(const QString& scriptText, const QString& idPrefix,
                                     const QString& correlationId,
                                     const QString& frameReportFile = QString());

    // Enqueue several render jobs all-or-nothing: capacity for every script
    // is checked and they are enqueued under one lock, so a full queue
    // rejects the whole batch and enqueues none (9qph). An identical retry
    // of a rejected batch is therefore safe. On success the returned vector
    // has one accepted result per script, in order; on failure it holds a
    // single rejected result carrying the error.
    QVector<SubmitResult> submitRenderBatch(const QStringList& scriptTexts,
                                            const QString& idPrefix,
                                            const QString& correlationId);

    // All five methods below are safe to call from HTTP threads. Studio 6 may
    // ingest report JSON here because QJsonDocument is reentrant. Studio 4
    // leaves report parsing to the main-thread completion path because its
    // JsonStd parser constructs a thread-affine QScriptEngine.
    std::pair<int, std::string> getStatusJson(const std::string& requestId);
    // With doWait, polls until the job is final, timeoutSec passes, or
    // isClientGone() reports the client disconnected (then stops waiting).
    std::pair<int, std::string> getResultJson(const std::string& requestId, bool doWait, int timeoutSec,
                                              const std::function<bool()>& isClientGone = std::function<bool()>());
    // *cancelledQueuedRender (optional) is set when a render was cancelled
    // before it started, so the caller can end its progress stream.
    std::pair<int, std::string> cancelJson(const std::string& requestId, const std::string& clientIP,
                                           bool* cancelledQueuedRender = nullptr);
    std::pair<int, std::string> cancelRenderJson(const std::string& requestId, const std::string& clientIP,
                                                 bool* cancelledQueuedRender = nullptr);
    std::string                 listJson(const std::string& statusFilter);

    // ── Artifacts (GET /artifacts/...) — HTTP threads ─────────────────────
    //
    // A job's artifacts are exactly its output manifest: outputs declared in
    // its report file ("output"/"manifest" events) plus, for render jobs, the
    // output_path/output_paths its result returned. Each manifest entry has a
    // stable "artifact_id" (its position) and a "url". Nothing outside the
    // manifest can be looked up, so no client-supplied path is ever opened.
    enum ArtifactLookup { ARTIFACT_FOUND, ARTIFACT_JOB_NOT_FOUND, ARTIFACT_NOT_DECLARED };
    ArtifactLookup findArtifact(const std::string& requestId, const std::string& artifactId,
                                QString& outPath);
    // Copy of the job's manifest entries and status; false if the job is unknown.
    bool artifactManifest(const std::string& requestId, QVariantList& outEntries,
                          QString& outStatus);

    // ── Main-thread API ────────────────────────────────────────────────────

    // Dequeue next QUEUED request into outId/outScript/outScriptFile/outArgs.
    // Sets m_currentId and returns true if work was found; false otherwise.
    bool dequeueNext(QString& outId, QString& outScript, QString& outScriptFile,
                     QVariantMap& outArgs);

    // Mark the running request as RUNNING (sets startedAt).
    void markRunning(const QString& id);

    // Frame-boundary progress for an animation render: frame N of total is
    // about to start (1-based). Sets progress to (frame-1)/total and the
    // observation detail to {current, total, frame, phase, message}. No-op if
    // the request isn't currently RUNNING (e.g. late call after cancel/timeout).
    void updateFrameProgress(const QString& id, int frame, int total);

    // HTTP threads: the frame an animation render last reported starting
    // (1-based) and its total. On Studio 6 this ingests the server-owned frame
    // report first, the same way status polling does, so the SSE progress
    // stream can see frames the shimmed print() never delivers. Returns false
    // when the job is unknown, isn't frame-tracked, or no frame has started.
    bool frameProgress(const QString& id, int* frame, int* total);

    // Record that the job currently on the main thread did something (it
    // printed a line). Feeds last_activity_at. No-op when nothing is running.
    void touchCurrent();

    // Record the real outcome after script execution returns. Accepts a
    // request that is RUNNING, CANCEL_REQUESTED or STALE; a cancel request or
    // stale timeout that happened mid-run selects the *_after_* variants (or
    // CANCELLED when a render was actually aborted) instead of discarding the
    // outcome. outWasCancelled is true only when the final status is CANCELLED.
    void markCompleted(const QString& id, bool executed, const QVariant& result,
                       const QStringList& output, const QString& error,
                       bool& outWasCancelled);

    // Mark a request CANCELLED (used for queued requests cancelled before
    // they were dequeued, or for immediate queue removal).
    void markCancelled(const QString& id, const QString& reason);

    // Release m_currentId so the next processNextAsyncRequest can dequeue.
    void clearCurrent();

    // Returns true if cancelRequested is set for this request (under mutex).
    bool isCancelRequested(const QString& id) const;

    // Remove completed/failed/cancelled entries older than ttlMs.
    // Called from cleanup timer on the main thread. Returns count removed.
    int cleanupExpired(qint64 ttlMs = ServerConfig::ASYNC_RESULT_TTL_SEC * 1000LL);

    // Mark any request stuck in RUNNING/CANCEL_REQUESTED for longer than
    // staleMs as STALE. Covers the case where the underlying DazScript call
    // (e.g. a render blocked behind a DAZ Studio modal dialog) never returns:
    // without this, GET /requests/:id would report "running" forever. STALE
    // ends long-poll waits and reports success:false, but it is not final --
    // it cannot un-block the main thread, and if the blocked call eventually
    // returns, markCompleted() records completed_after_stale (or failed).
    // Called from cleanup timer on the main thread. Returns count marked stale.
    int failStaleRunning(qint64 staleMs);

    // Mark all QUEUED and RUNNING requests as CANCELLED. Call on server stop
    // so that poll results after restart show the correct terminal state.
    void cancelAllPending(const QString& reason = "Server stopped");

private:
    // QUEUED -> RUNNING -> COMPLETED | FAILED
    // QUEUED -> CANCELLED                       (cancelled before it started)
    // RUNNING -> CANCEL_REQUESTED -> CANCELLED  (render actually aborted)
    //                            -> COMPLETED_AFTER_CANCEL_REQUEST | FAILED
    // RUNNING|CANCEL_REQUESTED -> STALE -> COMPLETED_AFTER_STALE | FAILED
    //                                      (or the cancel variants above)
    // A running script can't be interrupted, so cancel only *requests* a stop;
    // the status reports what really happened once the script returns.
    enum RequestStatus {
        REQUEST_QUEUED,
        REQUEST_RUNNING,
        REQUEST_CANCEL_REQUESTED,
        REQUEST_STALE,
        REQUEST_COMPLETED,
        REQUEST_FAILED,
        REQUEST_CANCELLED,
        REQUEST_COMPLETED_AFTER_CANCEL_REQUEST,
        REQUEST_COMPLETED_AFTER_STALE
    };

    static bool isTerminal(RequestStatus s);
    // Main thread still owns the work (markCompleted() will be called).
    static bool isActive(RequestStatus s)
    { return s == REQUEST_RUNNING || s == REQUEST_CANCEL_REQUESTED || s == REQUEST_STALE; }

    // How a job reports progress, fixed at submission (progress_source).
    enum ProgressSource { PROGRESS_NONE, PROGRESS_REPORT, PROGRESS_FRAMES };

    struct AsyncRequest {
        AsyncRequest()
            : status(REQUEST_QUEUED), requestType(REQUEST_TYPE_SCRIPT)
            , scriptExecuted(false), progress(0.0)
            , submittedAt(0), startedAt(0), completedAt(0), reportOffset(0)
            , logTotal(0), cancelRequested(0), cancelRequestedAt(0), staleAt(0)
            , lastActivityAt(0), progressSource(PROGRESS_NONE), ownsReportFile(false)
        {}

        QString       id;
        QString       correlationId;
        QString       serverInstanceId;
        RequestStatus status;
        RequestType   requestType;
        QString       scriptText;
        QString       scriptFile;
        QString       reportFile;
        QVariantMap   args;
        QVariant      scriptResult;
        QStringList   outputLines;
        QString       error;
        bool          scriptExecuted;
        double        progress;
        qint64        submittedAt;
        qint64        startedAt;
        qint64        completedAt;
        qint64        reportOffset;
        QByteArray    reportRemainder;
        QVariantMap   progressDetail;
        QVariantList  logTail;
        QVariantList  outputManifest;
        int           logTotal;
        // Always read/written while holding m_mutex.
        int           cancelRequested;
        qint64        cancelRequestedAt;
        qint64        staleAt;
        // Latest sign of life: start, a printed line, a progress update, a
        // report-file write (its mtime) or completion. 0 until it starts.
        qint64        lastActivityAt;
        ProgressSource progressSource;
        // reportFile was created by the server (animation frame report), not
        // the client: hidden from the observation and deleted on expiry.
        bool          ownsReportFile;
    };

    std::string statusToString(RequestStatus s) const;
    std::pair<int, std::string> cancelImpl(const std::string& requestId, bool renderOnly,
                                           bool* cancelledQueuedRender);
    static std::string lifecycleTimesJson(const AsyncRequest& req);
    static std::string identityJson(const AsyncRequest& req);
    static std::string activityJson(const AsyncRequest& req);
    static void touchLocked(AsyncRequest& req, qint64 at);
    // HTTP worker, m_mutex NOT held (Studio 6; no-op on Studio 4): reads the
    // job report's new bytes without the lock, then applies them under it
    // unless another reader already consumed them (yau7.2.6).
    void prefetchReport(const QString& id);
    void prefetchAllReports();
    // MAIN THREAD (final ingestion in markCompleted), m_mutex held.
    void ingestReportLocked(AsyncRequest& req, bool final = false);
    // m_mutex held. Applies bytes read from req.reportFile starting at
    // req.reportOffset (or at 0 when the file was rewritten).
    void applyReportBytesLocked(AsyncRequest& req, bool rewritten, const QByteArray& data,
                                const QDateTime& modified, bool final);
    void applyReportEventLocked(AsyncRequest& req, const QVariantMap& event);
    void declareRenderOutputsLocked(AsyncRequest& req, const QVariant& result);
    void appendLogLocked(AsyncRequest& req, const QVariantMap& logEntry);
    std::string observationJson(const AsyncRequest& req) const;

    QObject* m_notifyTarget; // DzScriptServerPane*

    QMap<QString, AsyncRequest> m_requests;
    QQueue<QString>             m_queue;
    QString                     m_currentId;
    QString                     m_serverInstanceId;
    mutable QMutex              m_mutex;

    const int m_maxQueueDepth;
    const int m_maxTrackedRequests;
};
