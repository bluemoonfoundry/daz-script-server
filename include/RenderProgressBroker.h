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
//   notifyProgress()  — called on main thread for animation renders, once
//                       per frame boundary (see DzScriptServerPane::
//                       onMessagePosted's [DAZPY_FRAME] marker handling)
//   notifyCompleted() — called on main thread after successful render
//   notifyFailed()    — called on main thread after failed/cancelled render
//
// DAZ SDK reality: DzRenderer exposes no renderProgress(int) signal, and
// live testing confirmed Iray posts no parseable progress text through the
// debug-message channel either (see bd daz-script-server-88wm). So intra-
// frame percent is not obtainable; notifyProgress() only reports frame-level
// progress for multi-frame animation renders (single-frame renders still
// only get the 0% start / terminal finish events).

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

    // Main thread: frame-boundary progress for animation renders. frame is
    // 1-based (frame N of totalFrames about to start). Sends
    // percent = 100 * (frame-1) / totalFrames.
    void notifyProgress(const QString& requestId, int frame, int totalFrames);

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
