#pragma once
#include <QtCore/qobject.h>
#include <QtCore/qstring.h>
#include <QtCore/qmap.h>
#include <QtCore/qqueue.h>
#include <QtCore/qmutex.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qpair.h>
#include <QtCore/qvariant.h>
#include <QtCore/qstringlist.h>
#include <string>

// ─── AsyncRequestManager ─────────────────────────────────────────────────────
//
// THREADING MODEL:
//   HTTP threads : submit(), getStatusJson(), getResultJson(), cancelJson(),
//                  listJson() — all acquire m_mutex internally.
//   Main thread  : dequeueNext(), markRunning(), markCompleted(),
//                  markCancelled(), clearCurrent(), cleanupExpired()
//                  — these also acquire m_mutex but are only called from the
//                  Qt main thread (processNextAsyncRequest / cleanup timer).
//
// SIGNALS (cross-thread):
//   requestEnqueued()     → DzScriptServerPane::processNextAsyncRequest()
//                           via Qt::QueuedConnection — safe wakeup from HTTP thread.
//   killRenderRequested() → DzScriptServerPane::killRenderOnMainThread()
//                           via Qt::QueuedConnection — routes DAZ API call to
//                           main thread instead of calling from HTTP thread.
//   requestCompleted()    → lifecycle notification (informational).

class AsyncRequestManager : public QObject {
    Q_OBJECT

public:
    static const int DEFAULT_MAX_QUEUE_DEPTH      = 100;
    static const int DEFAULT_MAX_TRACKED_REQUESTS = 1000;

    explicit AsyncRequestManager(QObject* parent = nullptr);

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

    // Enqueue a new async request. Returns SubmitResult::accepted=false when
    // the queue is at capacity or too many requests are tracked.
    SubmitResult        submit(const QString& scriptText, const QVariantMap& args,
                               const QString& idPrefix);

    // All four methods below are safe to call from HTTP threads.
    QPair<int, QString> getStatusJson(const QString& requestId) const;
    QPair<int, QString> getResultJson(const QString& requestId, bool doWait, int timeoutSec);
    QPair<int, QString> cancelJson(const QString& requestId, const QString& clientIP);
    QString             listJson(const QString& statusFilter) const;

    // Live counters — acquire mutex.
    int getQueueDepth()   const;
    int getTotalTracked() const;

    // ── Main-thread API ────────────────────────────────────────────────────

    // Dequeue next QUEUED request into outId/outScript/outArgs.
    // Sets m_currentId and returns true if work was found; false otherwise.
    bool dequeueNext(QString& outId, QString& outScript, QVariantMap& outArgs);

    // Mark the running request as RUNNING (sets startedAt).
    void markRunning(const QString& id);

    // Mark the running request terminal after script execution.
    // outWasCancelled is true if cancelRequested was set mid-run.
    void markCompleted(const QString& id, bool executed, const QVariant& result,
                       const QStringList& output, const QString& error,
                       bool& outWasCancelled);

    // Mark a request CANCELLED (used for already-queued requests that had
    // cancelRequested set before dequeue, or for immediate queue removal).
    void markCancelled(const QString& id, const QString& reason);

    // Release m_currentId so processNextAsyncRequest can dequeue the next item.
    void clearCurrent();

    // Returns true if cancelRequested is set for this request (under mutex).
    bool isCancelRequested(const QString& id) const;

    // Remove completed/failed/cancelled entries older than ttlMs.
    // Called from cleanup timer on the main thread. Returns count removed.
    int cleanupExpired(qint64 ttlMs = 60LL * 60LL * 1000LL);

    // Mark all QUEUED and RUNNING requests as CANCELLED. Call when the server
    // shuts down so that any poll result after restart shows the correct state.
    void cancelAllPending(const QString& reason = "Server stopped");

signals:
    // Posted (QueuedConnection) to the main thread's event loop on each submit.
    void requestEnqueued();
    // Posted to the main thread when cancellation arrives for a RUNNING request,
    // so the DAZ killRender() call happens on the main thread rather than an
    // HTTP thread.
    void killRenderRequested();
    // Informational lifecycle signal.
    void requestCompleted(const QString& id, bool success);

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
            : status(REQUEST_QUEUED), scriptExecuted(false), progress(0.0)
            , submittedAt(0), startedAt(0), completedAt(0), cancelRequested(0)
        {}

        QString       id;
        RequestStatus status;
        QString       scriptText;
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

    QMap<QString, AsyncRequest> m_requests;
    QQueue<QString>             m_queue;
    QString                     m_currentId;
    mutable QMutex              m_mutex;

    int m_maxQueueDepth;
    int m_maxTrackedRequests;
};
