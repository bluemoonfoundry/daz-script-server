#pragma once
#include <QtCore/qstring.h>
#include <QtCore/qmap.h>
#include <QtCore/qqueue.h>
#include <QtCore/qmutex.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qpair.h>
#include <QtCore/qvariant.h>
#include <QtCore/qstringlist.h>
#include <string>
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
    static const int DEFAULT_MAX_QUEUE_DEPTH      = 100;
    static const int DEFAULT_MAX_TRACKED_REQUESTS = 1000;
    static const int RESULT_POLL_INTERVAL_MS      = 500; // Long-poll sleep interval in getResultJson()

    // notifyTarget must be a DzScriptServerPane* (QObject subclass).
    // Stored as QObject* to avoid the DAZ header dependency here.
    explicit AsyncRequestManager(QObject* notifyTarget);

    // Config — call before starting server; not guarded (write-once at init).
    void setMaxQueueDepth(int n)      { m_maxQueueDepth = n; }
    void setMaxTrackedRequests(int n) { m_maxTrackedRequests = n; }
    int  maxQueueDepth() const        { return m_maxQueueDepth; }
    int  maxTrackedRequests() const   { return m_maxTrackedRequests; }

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
    SubmitResult        submit(const QString& scriptText, const QString& scriptFile,
                               const QVariantMap& args, const QString& idPrefix);

    // Enqueue a render job. Same as submit() but tags the request as
    // REQUEST_TYPE_RENDER so cancel dispatch calls killRender() correctly.
    SubmitResult        submitRender(const QString& scriptText, const QString& idPrefix);

    // All four methods below are safe to call from HTTP threads (no Qt string ops).
    std::pair<int, std::string> getStatusJson(const std::string& requestId) const;
    std::pair<int, std::string> getResultJson(const std::string& requestId, bool doWait, int timeoutSec);
    std::pair<int, std::string> cancelJson(const std::string& requestId, const std::string& clientIP);
    std::pair<int, std::string> cancelRenderJson(const std::string& requestId, const std::string& clientIP);
    std::string                 listJson(const std::string& statusFilter) const;

    // Live counters — acquire mutex.
    int getQueueDepth()   const;
    int getTotalTracked() const;

    // ── Main-thread API ────────────────────────────────────────────────────

    // Dequeue next QUEUED request into outId/outScript/outScriptFile/outArgs.
    // Sets m_currentId and returns true if work was found; false otherwise.
    bool dequeueNext(QString& outId, QString& outScript, QString& outScriptFile,
                     QVariantMap& outArgs);

    // Mark the running request as RUNNING (sets startedAt).
    void markRunning(const QString& id);

    // Update progress (0.0-1.0) for the running request. No-op if the
    // request isn't currently RUNNING (e.g. late call after cancel/timeout).
    void updateProgress(const QString& id, double progress);

    // Mark the running request terminal after script execution.
    // outWasCancelled is true if cancelRequested was set mid-run.
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
    int cleanupExpired(qint64 ttlMs = 60LL * 60LL * 1000LL);

    // Mark any request stuck in RUNNING for longer than staleMs as FAILED.
    // Covers the case where the underlying DazScript call (e.g. a render
    // that ends up blocked behind a DAZ Studio modal dialog) never returns:
    // without this, GET /requests/:id would report "running" forever. This
    // only updates the client-visible status -- it cannot un-block the main
    // thread, so if the blocked call eventually does return, markCompleted()
    // is a no-op for a request already in this terminal state (see markCompleted).
    // Called from cleanup timer on the main thread. Returns count marked failed.
    int failStaleRunning(qint64 staleMs);

    // Mark all QUEUED and RUNNING requests as CANCELLED. Call on server stop
    // so that poll results after restart show the correct terminal state.
    void cancelAllPending(const QString& reason = "Server stopped");

private:
    enum RequestStatus {
        REQUEST_QUEUED,
        REQUEST_RUNNING,
        REQUEST_COMPLETED,
        REQUEST_FAILED,
        REQUEST_CANCELLED
    };

    struct AsyncRequest {
        AsyncRequest()
            : status(REQUEST_QUEUED), requestType(REQUEST_TYPE_SCRIPT)
            , scriptExecuted(false), progress(0.0)
            , submittedAt(0), startedAt(0), completedAt(0), cancelRequested(0)
        {}

        QString       id;
        RequestStatus status;
        RequestType   requestType;
        QString       scriptText;
        QString       scriptFile;
        QVariantMap   args;
        QVariant      scriptResult;
        QStringList   outputLines;
        QString       error;
        bool          scriptExecuted;
        double        progress;
        qint64        submittedAt;
        qint64        startedAt;
        qint64        completedAt;
        // Always read/written while holding m_mutex.
        int           cancelRequested;
    };

    std::string statusToString(RequestStatus s) const;

    QObject* m_notifyTarget; // DzScriptServerPane*

    QMap<QString, AsyncRequest> m_requests;
    QQueue<QString>             m_queue;
    QString                     m_currentId;
    mutable QMutex              m_mutex;

    int m_maxQueueDepth;
    int m_maxTrackedRequests;
};
