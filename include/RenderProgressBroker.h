#pragma once
#include <QtCore/qmap.h>
#include <QtCore/qmutex.h>
#include <QtCore/qlist.h>
#include <QtCore/qstring.h>

// Full definition needed for QList<SubscriberQueue*> member
#include "SceneEventBroker.h"

// Per-render SSE progress broker.
//
// Lifecycle per request:
//   setOutputPath()   — called on main thread when render is enqueued
//   watchRequest()    — called from HTTP thread; registers a subscriber queue
//   notifyStarted()   — called on main thread when render begins executing
//   notifyCompleted() — called on main thread after successful render
//   notifyFailed()    — called on main thread after failed/cancelled render
//
// DAZ SDK reality: DzRenderer exposes no renderProgress(int) signal, so we
// emit a single progress event at 0% on start and a terminal event on finish.
// Real per-percent progress would require a private renderer plugin hook.

class RenderProgressBroker {
public:
    RenderProgressBroker();

    // Main thread: store output_path when the render job is enqueued.
    void setOutputPath(const QString& requestId, const QString& outputPath);

    // HTTP thread: register a queue to watch a render request.
    // If a terminal event is already stored, pushes it and closes the queue immediately.
    // Returns false if requestId is unknown (caller should 404).
    bool watchRequest(const QString& requestId, SubscriberQueue* queue);
    void unwatchRequest(const QString& requestId, SubscriberQueue* queue);

    // Main thread: lifecycle notifications from processNextAsyncRequest.
    void notifyStarted(const QString& requestId);
    void notifyCompleted(const QString& requestId, int durationMs);
    void notifyFailed(const QString& requestId, const QString& error, int durationMs);

    // Close all queues on server stop so SSE handler threads can exit.
    void stopAll();

private:
    // Push a non-terminal event to all watchers (does not close queues).
    void pushEvent(const QString& requestId, const QString& sseEvent);

    static QString makeEvent(const QString& type, const QString& dataJson);

    struct RequestWatch {
        QString                 outputPath;
        QString                 terminalEvent; // non-empty once complete/error
        QList<SubscriberQueue*> queues;
    };
    QMap<QString, RequestWatch> m_watches;
    mutable QMutex              m_mutex;
};
