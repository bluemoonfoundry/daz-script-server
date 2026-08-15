#pragma once
#include <deque>
#include <dzgeneraldefs.h>  // DzTime typedef (int), DZ_TICKS_PER_SECOND
#include <QtCore/qobject.h>
#include <QtCore/qmutex.h>
#include <QtCore/qwaitcondition.h>
#include <QtCore/qstring.h>
#include <QtCore/qlist.h>
#include <QtCore/qtimer.h>
#include <QtCore/qatomic.h>
#include <string>

// Forward declarations — full headers included in SceneEventBroker.cpp
class DzNode;
class DzSkeleton;
class DzLight;
class DzCamera;
class DzRenderer;
class DzRenderMgr;

// ─── Event filter categories ──────────────────────────────────────────────────
// Bitmask values passed to SubscriberQueue to control which event categories
// are delivered to each SSE client.
namespace SceneEventFilter {
    enum Category {
        None      = 0x00,
        Node      = 0x01,
        Skeleton  = 0x02,
        Light     = 0x04,
        Camera    = 0x08,
        Selection = 0x10,
        Scene     = 0x20,
        Time      = 0x40,
        Render    = 0x80,
        All       = 0xFF
    };
}

// ─── Main-thread busy state ────────────────────────────────────────────────
// Tracks whether the main thread is currently inside a long synchronous
// operation (scene load/save/clear, render) so HTTP handlers can fail fast
// instead of blocking indefinitely on Qt::BlockingQueuedConnection.
namespace MainThreadBusy {
    enum Reason {
        Idle = 0,
        SceneLoading,
        SceneSaving,
        SceneClearing,
        Rendering
    };

    // Pure function over a plain literal — safe to call from any thread.
    inline std::string reasonMessage(Reason r) {
        switch (r) {
        case SceneLoading:  return "DAZ Studio is currently loading a scene";
        case SceneSaving:   return "DAZ Studio is currently saving a scene";
        case SceneClearing: return "DAZ Studio is currently clearing the scene";
        case Rendering:     return "DAZ Studio is currently rendering";
        default:            return "DAZ Studio is busy";
        }
    }
}

// ─── SubscriberQueue ──────────────────────────────────────────────────────────
// Thread-safe event queue — one instance per connected SSE client.
//   push()  : called from the Qt main thread (inside SceneEventBroker slots).
//   pop()   : called from the HTTP handler thread; blocks until an event
//             arrives, the timeout elapses, or close() is called.
//   close() : called by SceneEventBroker::stop() to unblock all waiting
//             pop() calls so SSE handler threads can exit cleanly.
class SubscriberQueue {
public:
    explicit SubscriberQueue(int filterMask = SceneEventFilter::All);

    void    push(const QString& event);  // main thread
    QString pop(int timeoutMs);          // HTTP thread; "" on timeout or close
    void    close();                     // unblocks pop(), marks queue done

    int  filterMask() const { return m_filterMask; }
    bool isClosed()   const;

private:
    std::deque<QString> m_queue;
    mutable QMutex      m_mutex;
    QWaitCondition      m_cond;
    int                 m_filterMask;
    bool                m_closed;
};

// ─── SceneEventBroker ─────────────────────────────────────────────────────────
// Lives on the Qt main thread. Connects to DzScene signals on start() and
// dispatches JSON-serialized events to all registered SubscriberQueues.
// Debounces high-frequency signals (timeChanging, nodeSelectionListChanged)
// before dispatching so SSE clients are not flooded during playback or
// interactive scene editing.
class SceneEventBroker : public QObject {
    Q_OBJECT
public:
    explicit SceneEventBroker(QObject* parent = nullptr);
    ~SceneEventBroker();

    // Connect to DzScene signals. Call after the HTTP server is started.
    void start();
    // Disconnect signals, close all subscriber queues (unblocks SSE handlers).
    void stop();

    // Called from HTTP handler threads — acquires m_subscriberMutex internally.
    void registerSubscriber(SubscriberQueue* queue);
    void unregisterSubscriber(SubscriberQueue* queue);

    // Returns the current number of registered SSE clients.  Thread-safe.
    int subscriberCount() const;

    // Thread-safe (QAtomicInt) — safe to call from any HTTP worker thread.
    bool isBusy() const {
        return m_busyDepth.fetchAndAddOrdered(0) > 0;
    }
    MainThreadBusy::Reason busyReason() const {
        return static_cast<MainThreadBusy::Reason>(m_busyReason.fetchAndAddOrdered(0));
    }

    // Nested operations (e.g. a scene clear that runs inside a scene load)
    // must not let the inner operation's finish prematurely mark the main
    // thread idle. enterBusy()/exitBusy() track a depth counter alongside
    // the reason of the outermost active operation: only a 0->1 transition
    // records the reason, and only a 1->0 transition clears it, so nested
    // Starting/Finished pairs are absorbed without affecting busy state.
    //
    // Public so main-thread HTTP handlers can bracket busy state explicitly
    // for operations DzScene's own signals don't reliably cover (e.g. a
    // QFile::copy-based save shortcut that never calls DzScene::saveScene()).
    // Main thread only — matched enter/exit calls (ideally via an RAII guard)
    // are required to keep the depth counter balanced.
    void enterBusy(MainThreadBusy::Reason reason) {
        if (m_busyDepth.fetchAndAddOrdered(1) == 0) {
            m_busyReason.fetchAndStoreOrdered(static_cast<int>(reason));
        }
    }
    void exitBusy() {
        if (m_busyDepth.fetchAndAddOrdered(-1) == 1) {
            m_busyReason.fetchAndStoreOrdered(static_cast<int>(MainThreadBusy::Idle));
        }
    }

private slots:
    // Scene lifecycle
    void onSceneLoadStarting();
    void onSceneLoaded();
    void onSceneSaveStarting(const QString& filename);
    void onSceneSaved(const QString& filename);
    void onSceneClearStarting();
    void onSceneCleared();

    // Nodes
    void onNodeAdded(DzNode* node);
    void onNodeRemoved(DzNode* node);

    // Skeletons
    void onSkeletonAdded(DzSkeleton* node);
    void onSkeletonRemoved(DzSkeleton* node);

    // Lights
    void onLightAdded(DzLight* node);
    void onLightRemoved(DzLight* node);

    // Cameras
    void onCameraAdded(DzCamera* node);
    void onCameraRemoved(DzCamera* node);

    // Selection
    void onSelectionListChanged();
    void onSelectionDebounced();
    void onPrimarySelectionChanged(DzNode* node);

    // Time (timeChanging is debounced; timeChanged fires immediately)
    void onTimeChanging(DzTime newTime);
    void onTimeChanged(DzTime time);
    void onTimeDebounced();
    void onPlaybackStarted();
    void onPlaybackFinished();

    // Render
    void onAboutToRender(DzRenderer* r);
    void onRenderFinished(DzRenderer* r);
    // DzRenderMgr's renderFinished(bool) is the authoritative render-lifecycle
    // signal: unlike DzScene::renderFinished(DzRenderer*), it fires even when
    // the render errors out (DAZ Studio pops a blocking modal dialog in that
    // case, which can prevent DzScene::renderFinished from ever being emitted).
    // Whichever "finished" signal arrives first clears the render busy state;
    // see m_renderBusy.
    void onRenderMgrFinished(bool succeeded);

private:
    void    dispatch(int categoryBit, const QString& event);
    QString makeEvent(const QString& type, const QString& dataJson) const;
    QString nodeInfoJson(DzNode* node) const;

    QList<SubscriberQueue*> m_subscribers;
    mutable QMutex          m_subscriberMutex;

    QTimer*  m_pTimeDebounce;       // 150 ms single-shot, debounces timeChanging
    QTimer*  m_pSelectionDebounce;  // 50 ms single-shot, debounces selection bursts
    DzTime   m_pendingTime;
    bool     m_started;
    bool     m_renderBusy;            // guards against double enterBusy()/exitBusy() from the two render-finished signals
    mutable QAtomicInt m_busyDepth;   // count of active nested busy operations; written on main thread only
    mutable QAtomicInt m_busyReason;  // MainThreadBusy::Reason of the outermost active operation
};
