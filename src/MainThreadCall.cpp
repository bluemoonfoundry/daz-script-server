#include "MainThreadCall.h"
#include <QtCore/qelapsedtimer.h>
#include <QtCore/qmetaobject.h>

namespace MainThreadCall {

// How often a waiting worker re-checks the client socket and the deadline.
static const int kPollSliceMs = 250;

void release(Call* call)
{
    if (call && !call->refs.deref())
        delete call;
}

void runOnMainThread(DzScriptServerPane* pane, Call* call)
{
    if (!call) return;
    if (call->state.testAndSetOrdered(Pending, Running)) {
        call->result = call->invoke(pane);
        call->done.release();
    }
    release(call);
}

Outcome post(DzScriptServerPane* pane, Call* call, int queueTimeoutMs,
             const std::function<bool()>& isClientGone, HttpResult* out)
{
    if (!QMetaObject::invokeMethod(pane, "handleMainThreadCall", Qt::QueuedConnection,
            Q_ARG(qulonglong, static_cast<qulonglong>(reinterpret_cast<quintptr>(call))))) {
        release(call);   // the main thread's reference
        release(call);   // ours
        return PostFailed;
    }

    QElapsedTimer waited;
    waited.start();
    for (;;) {
        if (call->done.tryAcquire(1, kPollSliceMs))
            break;
        if (call->state.testAndSetOrdered(Running, Running)) {
            // The main thread has started it: the work is really in progress,
            // so wait for it however long it takes.
            call->done.acquire();
            break;
        }
        const bool giveUp = waited.elapsed() >= queueTimeoutMs
                         || (isClientGone && isClientGone());
        if (giveUp && call->state.testAndSetOrdered(Pending, Abandoned)) {
            release(call);   // main thread skips it and drops its own reference
            return GaveUp;
        }
        // Lost the race to the main thread: the next pass sees Running.
    }

    *out = call->result;
    release(call);
    return Completed;
}

} // namespace MainThreadCall
