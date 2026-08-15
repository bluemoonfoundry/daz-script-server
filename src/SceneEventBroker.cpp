#include "SceneEventBroker.h"
#include "JsonBuilder.h"

#include <dzscene.h>
#include <dznode.h>
#include <dzskeleton.h>
#include <dzlight.h>
#include <dzcamera.h>
#include <dzrenderer.h>
#include <dzrendermgr.h>
#include <dzapp.h>

#include <QtCore/qdatetime.h>

// ─── SubscriberQueue ──────────────────────────────────────────────────────────

SubscriberQueue::SubscriberQueue(int filterMask)
    : m_filterMask(filterMask)
    , m_closed(false)
{}

void SubscriberQueue::push(const QString& event) {
    QMutexLocker lock(&m_mutex);
    if (m_closed) return;
    m_queue.push_back(event);
    m_cond.wakeOne();
}

QString SubscriberQueue::pop(int timeoutMs) {
    QMutexLocker lock(&m_mutex);
    if (m_queue.empty()) {
        if (m_closed) return QString();
        m_cond.wait(&m_mutex, static_cast<unsigned long>(timeoutMs));
    }
    if (m_queue.empty()) return QString();
    QString event = m_queue.front();
    m_queue.pop_front();
    return event;
}

void SubscriberQueue::close() {
    QMutexLocker lock(&m_mutex);
    m_closed = true;
    m_cond.wakeAll();
}

bool SubscriberQueue::isClosed() const {
    QMutexLocker lock(&m_mutex);
    return m_closed;
}

// ─── SceneEventBroker ─────────────────────────────────────────────────────────

SceneEventBroker::SceneEventBroker(QObject* parent)
    : QObject(parent)
    , m_pTimeDebounce(nullptr)
    , m_pSelectionDebounce(nullptr)
    , m_pendingTime(0)
    , m_started(false)
    , m_renderBusy(false)
    , m_busyDepth(0)
    , m_busyReason(MainThreadBusy::Idle)
{
    m_pTimeDebounce = new QTimer(this);
    m_pTimeDebounce->setSingleShot(true);
    m_pTimeDebounce->setInterval(150);
    connect(m_pTimeDebounce, SIGNAL(timeout()), this, SLOT(onTimeDebounced()));

    m_pSelectionDebounce = new QTimer(this);
    m_pSelectionDebounce->setSingleShot(true);
    m_pSelectionDebounce->setInterval(50);
    connect(m_pSelectionDebounce, SIGNAL(timeout()), this, SLOT(onSelectionDebounced()));
}

SceneEventBroker::~SceneEventBroker() {
    if (m_started) stop();
}

void SceneEventBroker::start() {
    if (m_started || !dzScene) return;
    DzScene* scene = dzScene;

    // Scene lifecycle
    connect(scene, SIGNAL(sceneLoadStarting()),               this, SLOT(onSceneLoadStarting()));
    connect(scene, SIGNAL(sceneLoaded()),                     this, SLOT(onSceneLoaded()));
    connect(scene, SIGNAL(sceneSaveStarting(const QString&)), this, SLOT(onSceneSaveStarting(const QString&)));
    connect(scene, SIGNAL(sceneSaved(const QString&)),        this, SLOT(onSceneSaved(const QString&)));
    connect(scene, SIGNAL(sceneClearStarting()),              this, SLOT(onSceneClearStarting()));
    connect(scene, SIGNAL(sceneCleared()),                    this, SLOT(onSceneCleared()));

    // Nodes
    connect(scene, SIGNAL(nodeAdded(DzNode*)),                this, SLOT(onNodeAdded(DzNode*)));
    connect(scene, SIGNAL(nodeRemoved(DzNode*)),              this, SLOT(onNodeRemoved(DzNode*)));

    // Skeletons
    connect(scene, SIGNAL(skeletonAdded(DzSkeleton*)),        this, SLOT(onSkeletonAdded(DzSkeleton*)));
    connect(scene, SIGNAL(skeletonRemoved(DzSkeleton*)),      this, SLOT(onSkeletonRemoved(DzSkeleton*)));

    // Lights
    connect(scene, SIGNAL(lightAdded(DzLight*)),              this, SLOT(onLightAdded(DzLight*)));
    connect(scene, SIGNAL(lightRemoved(DzLight*)),            this, SLOT(onLightRemoved(DzLight*)));

    // Cameras
    connect(scene, SIGNAL(cameraAdded(DzCamera*)),            this, SLOT(onCameraAdded(DzCamera*)));
    connect(scene, SIGNAL(cameraRemoved(DzCamera*)),          this, SLOT(onCameraRemoved(DzCamera*)));

    // Selection
    connect(scene, SIGNAL(nodeSelectionListChanged()),         this, SLOT(onSelectionListChanged()));
    connect(scene, SIGNAL(primarySelectionChanged(DzNode*)),  this, SLOT(onPrimarySelectionChanged(DzNode*)));

    // Time
    connect(scene, SIGNAL(timeChanging(DzTime)),              this, SLOT(onTimeChanging(DzTime)));
    connect(scene, SIGNAL(timeChanged(DzTime)),               this, SLOT(onTimeChanged(DzTime)));
    connect(scene, SIGNAL(playbackStarted()),                  this, SLOT(onPlaybackStarted()));
    connect(scene, SIGNAL(playbackFinished()),                 this, SLOT(onPlaybackFinished()));

    // Render
    connect(scene, SIGNAL(aboutToRender(DzRenderer*)),        this, SLOT(onAboutToRender(DzRenderer*)));
    connect(scene, SIGNAL(renderFinished(DzRenderer*)),       this, SLOT(onRenderFinished(DzRenderer*)));

    // DzRenderMgr::renderFinished(bool) is connected as a second, guaranteed
    // exit path: DzScene::renderFinished(DzRenderer*) is not emitted when a
    // render errors out and DAZ Studio blocks the main thread behind its
    // modal "Error during rendering!" dialog, which otherwise leaves the
    // plugin's busy state (and therefore /execute) stuck forever.
    DzRenderMgr* renderMgr = dzApp ? dzApp->getRenderMgr() : nullptr;
    if (renderMgr) {
        connect(renderMgr, SIGNAL(renderFinished(bool)), this, SLOT(onRenderMgrFinished(bool)));
    }

    m_started = true;
}

void SceneEventBroker::stop() {
    if (!m_started) return;

    if (dzScene) {
        disconnect(dzScene, nullptr, this, nullptr);
    }

    DzRenderMgr* renderMgr = dzApp ? dzApp->getRenderMgr() : nullptr;
    if (renderMgr) {
        disconnect(renderMgr, nullptr, this, nullptr);
    }

    m_pTimeDebounce->stop();
    m_pSelectionDebounce->stop();
    m_started = false;

    // Close all subscriber queues — unblocks waiting pop() calls so SSE
    // handler threads can detect the shutdown and exit cleanly.
    QMutexLocker lock(&m_subscriberMutex);
    for (int i = 0; i < m_subscribers.size(); ++i)
        m_subscribers[i]->close();
}

void SceneEventBroker::registerSubscriber(SubscriberQueue* queue) {
    QMutexLocker lock(&m_subscriberMutex);
    m_subscribers.append(queue);
}

void SceneEventBroker::unregisterSubscriber(SubscriberQueue* queue) {
    QMutexLocker lock(&m_subscriberMutex);
    m_subscribers.removeAll(queue);
}

int SceneEventBroker::subscriberCount() const {
    QMutexLocker lock(&m_subscriberMutex);
    return m_subscribers.size();
}

void SceneEventBroker::dispatch(int categoryBit, const QString& event) {
    QMutexLocker lock(&m_subscriberMutex);
    for (int i = 0; i < m_subscribers.size(); ++i) {
        if (m_subscribers[i]->filterMask() & categoryBit)
            m_subscribers[i]->push(event);
    }
}

QString SceneEventBroker::makeEvent(const QString& type, const QString& dataJson) const {
    qint64 ts = QDateTime::currentMSecsSinceEpoch();
    // type is always a hardcoded string literal — no escaping needed.
    return QString("{\"type\":\"%1\",\"ts\":%2,\"data\":%3}").arg(type).arg(ts).arg(dataJson);
}

QString SceneEventBroker::nodeInfoJson(DzNode* node) const {
    if (!node) return "{}";
    JsonBuilder j;
    j.startObject();
    // Pointer address is the stable per-session unique identifier for a node.
    j.addMember("node_id", QString("0x%1").arg(reinterpret_cast<quintptr>(node), 0, 16));
    j.addMember("node_name", node->getLabel());
    j.addMember("node_type", QString(node->metaObject()->className()));
    j.finishObject();
    return j.toString();
}

// ─── Scene lifecycle ──────────────────────────────────────────────────────────

void SceneEventBroker::onSceneLoadStarting() {
    enterBusy(MainThreadBusy::SceneLoading);
    dispatch(SceneEventFilter::Scene, makeEvent("scene.loading", "{}"));
}

void SceneEventBroker::onSceneLoaded() {
    exitBusy();
    dispatch(SceneEventFilter::Scene, makeEvent("scene.loaded", "{}"));
}

void SceneEventBroker::onSceneSaveStarting(const QString& filename) {
    enterBusy(MainThreadBusy::SceneSaving);
    JsonBuilder j;
    j.startObject();
    j.addMember("filename", filename);
    j.finishObject();
    dispatch(SceneEventFilter::Scene, makeEvent("scene.saving", j.toString()));
}

void SceneEventBroker::onSceneSaved(const QString& filename) {
    exitBusy();
    JsonBuilder j;
    j.startObject();
    j.addMember("filename", filename);
    j.finishObject();
    dispatch(SceneEventFilter::Scene, makeEvent("scene.saved", j.toString()));
}

void SceneEventBroker::onSceneClearStarting() {
    enterBusy(MainThreadBusy::SceneClearing);
    dispatch(SceneEventFilter::Scene, makeEvent("scene.clear_starting", "{}"));
}

void SceneEventBroker::onSceneCleared() {
    exitBusy();
    dispatch(SceneEventFilter::Scene, makeEvent("scene.cleared", "{}"));
}

// ─── Nodes ────────────────────────────────────────────────────────────────────

void SceneEventBroker::onNodeAdded(DzNode* node) {
    dispatch(SceneEventFilter::Node, makeEvent("node.added", nodeInfoJson(node)));
}

void SceneEventBroker::onNodeRemoved(DzNode* node) {
    dispatch(SceneEventFilter::Node, makeEvent("node.removed", nodeInfoJson(node)));
}

// ─── Skeletons ────────────────────────────────────────────────────────────────

void SceneEventBroker::onSkeletonAdded(DzSkeleton* node) {
    dispatch(SceneEventFilter::Skeleton, makeEvent("skeleton.added", nodeInfoJson(node)));
}

void SceneEventBroker::onSkeletonRemoved(DzSkeleton* node) {
    dispatch(SceneEventFilter::Skeleton, makeEvent("skeleton.removed", nodeInfoJson(node)));
}

// ─── Lights ───────────────────────────────────────────────────────────────────

void SceneEventBroker::onLightAdded(DzLight* node) {
    dispatch(SceneEventFilter::Light, makeEvent("light.added", nodeInfoJson(node)));
}

void SceneEventBroker::onLightRemoved(DzLight* node) {
    dispatch(SceneEventFilter::Light, makeEvent("light.removed", nodeInfoJson(node)));
}

// ─── Cameras ──────────────────────────────────────────────────────────────────

void SceneEventBroker::onCameraAdded(DzCamera* node) {
    dispatch(SceneEventFilter::Camera, makeEvent("camera.added", nodeInfoJson(node)));
}

void SceneEventBroker::onCameraRemoved(DzCamera* node) {
    dispatch(SceneEventFilter::Camera, makeEvent("camera.removed", nodeInfoJson(node)));
}

// ─── Selection ────────────────────────────────────────────────────────────────

void SceneEventBroker::onSelectionListChanged() {
    // Restart the debounce timer; multi-select operations burst this signal.
    m_pSelectionDebounce->start();
}

void SceneEventBroker::onSelectionDebounced() {
    dispatch(SceneEventFilter::Selection, makeEvent("selection.list_changed", "{}"));
}

void SceneEventBroker::onPrimarySelectionChanged(DzNode* node) {
    // primarySelectionChanged fires once per user action — no debounce needed.
    dispatch(SceneEventFilter::Selection,
             makeEvent("selection.primary_changed", nodeInfoJson(node)));
}

// ─── Time ─────────────────────────────────────────────────────────────────────

void SceneEventBroker::onTimeChanging(DzTime newTime) {
    // Fires every frame during playback. Store the latest value and restart
    // the debounce timer; one event is emitted after 150 ms of silence.
    m_pendingTime = newTime;
    m_pTimeDebounce->start();
}

void SceneEventBroker::onTimeChanged(DzTime time) {
    // Manual scrub: cancel the debounce and emit immediately.
    m_pTimeDebounce->stop();
    m_pendingTime = time;
    onTimeDebounced();
}

void SceneEventBroker::onTimeDebounced() {
    JsonBuilder j;
    j.startObject();
    j.addMember("time_ticks", static_cast<int>(m_pendingTime));
    j.addMember("time_secs",  static_cast<double>(m_pendingTime) / DZ_TICKS_PER_SECOND);
    j.finishObject();
    dispatch(SceneEventFilter::Time, makeEvent("time.changed", j.toString()));
}

void SceneEventBroker::onPlaybackStarted() {
    dispatch(SceneEventFilter::Time, makeEvent("playback.started", "{}"));
}

void SceneEventBroker::onPlaybackFinished() {
    dispatch(SceneEventFilter::Time, makeEvent("playback.finished", "{}"));
}

// ─── Render ───────────────────────────────────────────────────────────────────

void SceneEventBroker::onAboutToRender(DzRenderer* /*r*/) {
    if (!m_renderBusy) {
        enterBusy(MainThreadBusy::Rendering);
        m_renderBusy = true;
    }
    dispatch(SceneEventFilter::Render, makeEvent("render.started", "{}"));
}

void SceneEventBroker::onRenderFinished(DzRenderer* /*r*/) {
    if (m_renderBusy) {
        exitBusy();
        m_renderBusy = false;
    }
    dispatch(SceneEventFilter::Render, makeEvent("render.finished", "{}"));
}

// Guaranteed exit path — see the comment in start() where this is connected.
void SceneEventBroker::onRenderMgrFinished(bool succeeded) {
    if (m_renderBusy) {
        exitBusy();
        m_renderBusy = false;
    }
    JsonBuilder j;
    j.startObject();
    j.addMember("succeeded", succeeded);
    j.finishObject();
    dispatch(SceneEventFilter::Render, makeEvent("render.finished", j.toString()));
}

#include "moc_SceneEventBroker.cpp"
