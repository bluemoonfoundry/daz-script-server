#include "RenderProgressBroker.h"

#include <QtCore/qfileinfo.h>
#include <QtCore/qmutex.h>

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
    QString data = "{\"request_id\":\"" + requestId + "\",\"percent\":0}";
    pushEvent(requestId, makeEvent("progress", data));
}

void RenderProgressBroker::notifyCompleted(const QString& requestId, int durationMs)
{
    QString outputPath;
    {
        QMutexLocker lock(&m_mutex);
        if (m_watches.contains(requestId))
            outputPath = m_watches[requestId].outputPath;
    }

    qint64 fileSize = -1;
    if (!outputPath.isEmpty())
        fileSize = QFileInfo(outputPath).size();

    // Minimal JSON escaping for the path (backslashes on Windows).
    QString escapedPath = outputPath;
    escapedPath.replace("\\", "\\\\").replace("\"", "\\\"");

    QString data = "{\"request_id\":\"" + requestId
        + "\",\"output_path\":\"" + escapedPath
        + "\",\"file_size_bytes\":" + QString::number(fileSize)
        + ",\"duration_ms\":"      + QString::number(durationMs) + "}";
    QString event = makeEvent("complete", data);

    QList<SubscriberQueue*> queues;
    {
        QMutexLocker lock(&m_mutex);
        if (m_watches.contains(requestId)) {
            m_watches[requestId].terminalEvent = event;
            queues = m_watches[requestId].queues;
            m_watches[requestId].queues.clear();
        }
    }
    for (int i = 0; i < queues.size(); ++i) {
        queues[i]->push(event);
        queues[i]->close();
    }
}

void RenderProgressBroker::notifyFailed(const QString& requestId, const QString& error, int durationMs)
{
    QString escapedError = error;
    escapedError.replace("\\", "\\\\").replace("\"", "\\\"");

    QString data = "{\"request_id\":\"" + requestId
        + "\",\"error\":\""     + escapedError
        + "\",\"duration_ms\":" + QString::number(durationMs) + "}";
    QString event = makeEvent("error", data);

    QList<SubscriberQueue*> queues;
    {
        QMutexLocker lock(&m_mutex);
        if (m_watches.contains(requestId)) {
            m_watches[requestId].terminalEvent = event;
            queues = m_watches[requestId].queues;
            m_watches[requestId].queues.clear();
        }
    }
    for (int i = 0; i < queues.size(); ++i) {
        queues[i]->push(event);
        queues[i]->close();
    }
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
    QList<SubscriberQueue*> queues;
    {
        QMutexLocker lock(&m_mutex);
        if (!m_watches.contains(requestId)) return;
        queues = m_watches[requestId].queues;
    }
    for (int i = 0; i < queues.size(); ++i)
        queues[i]->push(sseEvent);
}

QString RenderProgressBroker::makeEvent(const QString& type, const QString& dataJson)
{
    return "event: " + type + "\ndata: " + dataJson + "\n\n";
}
