#include "MainThreadCall.h"
#include "ErrorResponse.h"
#include <exception>
#include <QtCore/qelapsedtimer.h>
#include <QtCore/qmetaobject.h>
#include <QtCore/qlist.h>

namespace MainThreadCall {

// How often a waiting worker re-checks the client socket and the deadline.
static const int kPollSliceMs = 250;

// Re-entrancy guard (daz-script-server-29gd). Main thread only.
namespace {
int g_scriptDepth = 0;
struct Deferred {
    DzScriptServerPane* pane;
    Call*               call;
};
QList<Deferred> g_deferred;

bool repost(DzScriptServerPane* pane, Call* call)
{
    return QMetaObject::invokeMethod(pane, "handleMainThreadCall", Qt::QueuedConnection,
        Q_ARG(qulonglong, static_cast<qulonglong>(reinterpret_cast<quintptr>(call))));
}
} // namespace

ScriptScope::ScriptScope()
{
    ++g_scriptDepth;
}

ScriptScope::~ScriptScope()
{
    if (--g_scriptDepth > 0 || g_deferred.isEmpty()) return;
    // The outermost script has returned: queue the held calls again, in
    // arrival order. Each is still Pending unless its worker gave up, in
    // which case runOnMainThread() just drops it.
    const QList<Deferred> held = g_deferred;
    g_deferred.clear();
    for (int i = 0; i < held.size(); ++i) {
        if (!repost(held[i].pane, held[i].call))
            release(held[i].call);   // its worker times out (GaveUp)
    }
}

bool scriptRunning()
{
    return g_scriptDepth > 0;
}

void release(Call* call)
{
    if (call && !call->refs.deref())
        delete call;
}

void runOnMainThread(DzScriptServerPane* pane, Call* call)
{
    if (!call) return;
    // A server script is running and pumped the event loop (Iray's DzProgress
    // does). Running the call now would nest inside that script, and a nested
    // DzScript::execute blocks forever on a lock the outer one holds. Hold it
    // until the script returns; it stays Pending, so its worker's queue
    // timeout still applies (29gd).
    if (g_scriptDepth > 0 && call->state.fetchAndAddOrdered(0) == Pending) {
        Deferred d = { pane, call };
        g_deferred.append(d);
        return;
    }
    if (call->state.testAndSetOrdered(Pending, Running)) {
        try {
            call->result = call->invoke(pane);
        } catch (const std::exception& e) {
            const std::string body = ErrorResponse::build(ErrorCode::INTERNAL_ERROR,
                std::string("main-thread handler threw: ") + e.what());
            call->result = HttpResult(500, QByteArray(body.c_str(), (int)body.size()));
        } catch (...) {
            const std::string body = ErrorResponse::build(ErrorCode::INTERNAL_ERROR,
                "main-thread handler threw an unknown exception");
            call->result = HttpResult(500, QByteArray(body.c_str(), (int)body.size()));
        }
        // Always wake the worker: it is blocked in done.acquire() once Running.
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
