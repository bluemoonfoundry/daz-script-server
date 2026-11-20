#include "RenderProgressBroker.h"
#include "JsonStd.h"

#include <QtCore/qfileinfo.h>
#include <QtCore/qmutex.h>

namespace {
// Full JSON string escaping (control chars included): a raw newline in an
// error message or path would break both the JSON and the SSE "data:" framing.
QString jsonEscape(const QString& s)
{
    const std::string escaped = JsonStd::escape(JsonStd::qstrToStd(s));
    return QString::fromUtf8(escaped.data(), static_cast<int>(escaped.size()));
}
}

RenderProgressBroker::RenderProgressBroker() {}

void RenderProgressBroker::setOutputPath(const QString& requestId, const QString& outputPath)
{
    QMutexLocker lock(&m_mutex);
    m_watches[requestId].outputPath = outputPath;
}

bool RenderProgressBroker::watchRequest(const QString& requestId, SubscriberQueue* queue)
{
    QMutexLocker lock(&m_mutex);
    if (!m_watches.contains(requestId)) return false;
    RequestWatch& w = m_watches[requestId];
    if (!w.terminalEvent.isEmpty()) {
        // Render already finished — deliver the stored terminal event immediately.
        queue->push(w.terminalEvent);
        queue->close();
        return true;
    }
    if (!w.lastProgressEvent.isEmpty())
        queue->push(w.lastProgressEvent);
    w.queues.append(queue);
    return true;
}

void RenderProgressBroker::unwatchRequest(const QString& requestId, SubscriberQueue* queue)
{
    QMutexLocker lock(&m_mutex);
    if (!m_watches.contains(requestId)) return;
    m_watches[requestId].queues.removeAll(queue);
}

void RenderProgressBroker::notifyStarted(const QString& requestId)
{
    QString data = "{\"request_id\":\"" + jsonEscape(requestId) + "\",\"percent\":0}";
    pushEvent(requestId, makeEvent("progress", data));
}

void RenderProgressBroker::notifyProgress(const QString& requestId, int frame, int totalFrames)
{
    if (frame < 1 || totalFrames < 1) return;
    double percent = 100.0 * (frame - 1) / totalFrames;
    QString data = "{\"request_id\":\"" + jsonEscape(requestId)
        + "\",\"percent\":" + QString::number(percent, 'f', 2)
        + ",\"frame\":" + QString::number(frame)
        + ",\"total_frames\":" + QString::number(totalFrames) + "}";
    QString event = makeEvent("progress", data);

    // Check-and-push under one lock so two callers reporting the same frame
    // can't both pass the check, and events reach queues in frame order.
    QMutexLocker lock(&m_mutex);
    if (!m_watches.contains(requestId)) return;
    RequestWatch& w = m_watches[requestId];
    if (!w.terminalEvent.isEmpty() || frame <= w.lastFrame) return;
    w.lastFrame         = frame;
    w.lastProgressEvent = event;
    for (int i = 0; i < w.queues.size(); ++i)
        w.queues[i]->push(event);
}

void RenderProgressBroker::notifyCompleted(const QString& requestId, int durationMs,
                                           const QStringList& outputFiles)
{
    QString outputPath;
    {
        QMutexLocker lock(&m_mutex);
        if (m_watches.contains(requestId))
            outputPath = m_watches[requestId].outputPath;
    }

    // Animation output paths are templates ("walk_{frame}.png") that never
    // exist on disk, so size the files the job actually wrote: the sum of its
    // declared outputs. Fall back to the stored path when nothing was declared.
    qint64 fileSize = -1;
    if (!outputFiles.isEmpty()) {
        fileSize = 0;
        for (int i = 0; i < outputFiles.size(); ++i)
            fileSize += QFileInfo(outputFiles[i]).size();
    } else if (!outputPath.isEmpty()) {
        fileSize = QFileInfo(outputPath).size();
    }

    QString data = "{\"request_id\":\"" + jsonEscape(requestId)
        + "\",\"output_path\":\"" + jsonEscape(outputPath)
        + "\",\"file_size_bytes\":" + QString::number(fileSize)
        + ",\"duration_ms\":"      + QString::number(durationMs) + "}";
    QString event = makeEvent("complete", data);

    publishTerminal(requestId, event);
}

void RenderProgressBroker::notifyFailed(const QString& requestId, const QString& error, int durationMs)
{
    QString data = "{\"request_id\":\"" + jsonEscape(requestId)
        + "\",\"error\":\""     + jsonEscape(error)
        + "\",\"duration_ms\":" + QString::number(durationMs) + "}";
    QString event = makeEvent("error", data);

    publishTerminal(requestId, event);
}

void RenderProgressBroker::stopAll()
{
    QMutexLocker lock(&m_mutex);
    for (QMap<QString, RequestWatch>::iterator it = m_watches.begin();
         it != m_watches.end(); ++it) {
        for (int i = 0; i < it->queues.size(); ++i)
            it->queues[i]->close();
        it->queues.clear();
    }
}

void RenderProgressBroker::pushEvent(const QString& requestId, const QString& sseEvent)
{
    // Push under the lock: the SSE release callback deletes its queue right
    // after unwatchRequest(), so a queue pointer is only valid while m_mutex
    // is held and the queue is still registered.
    QMutexLocker lock(&m_mutex);
    if (!m_watches.contains(requestId)) return;
    const QList<SubscriberQueue*>& queues = m_watches[requestId].queues;
    for (int i = 0; i < queues.size(); ++i)
        queues[i]->push(sseEvent);
}

void RenderProgressBroker::publishTerminal(const QString& requestId, const QString& sseEvent)
{
    // Same lifetime rule as pushEvent(): push and close before releasing
    // m_mutex, or a disconnecting client may delete its queue in between.
    QMutexLocker lock(&m_mutex);
    if (!m_watches.contains(requestId)) return;
    RequestWatch& w = m_watches[requestId];
    w.terminalEvent = sseEvent;
    for (int i = 0; i < w.queues.size(); ++i) {
        w.queues[i]->push(sseEvent);
        w.queues[i]->close();
    }
    w.queues.clear();
}

QString RenderProgressBroker::makeEvent(const QString& type, const QString& dataJson)
{
    return "event: " + type + "\ndata: " + dataJson + "\n\n";
}
