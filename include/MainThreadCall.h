#pragma once

// MainThreadCall — a sync HTTP handler's bounded, cancellable crossing to the
// main thread (daz-script-server-3w3y).
//
// Qt::BlockingQueuedConnection has no timeout: while the main thread is stuck
// in a long or hung script, every sync /execute behind it blocks forever and
// holds an ActiveRequestSlot, even after its client has gone, until the
// concurrent limit is exhausted and every request gets 429.
//
// A Call is posted with Qt::QueuedConnection instead. The worker waits in short
// slices and gives up (Pending -> Abandoned) when the client disconnects or the
// deadline passes. The main thread claims it (Pending -> Running) before doing
// any work, so an abandoned call never runs and a call that has started is
// always waited for. Exactly one side wins the compare-and-swap.
//
// Created with two references (worker + main thread); whoever drops the last
// one deletes it, so either side can leave first. Allocation and deletion both
// happen in this DLL.

#include "DzScriptServerPane.h"   // HttpResult
#include <QtCore/qatomic.h>
#include <QtCore/qsemaphore.h>
#include <functional>

namespace MainThreadCall {

enum State { Pending = 0, Running = 1, Abandoned = 2 };

struct Call {
    Call() : refs(2), state(Pending) {}
    virtual ~Call() {}

    // MAIN THREAD ONLY. Does the work; called only if the claim succeeded.
    virtual HttpResult invoke(DzScriptServerPane* pane) = 0;

    HttpResult result;      // set by the main thread before done.release()
    QSemaphore done;
    QAtomicInt refs;
    QAtomicInt state;

private:
    Call(const Call&);
    Call& operator=(const Call&);
};

// A Call that runs a function on the main thread. Capture Qt types
// (QByteArray, QPointer), never std::string built by Qt (CRT heap mismatch).
struct FunctionCall : Call {
    typedef std::function<HttpResult(DzScriptServerPane*)> Fn;
    explicit FunctionCall(const Fn& f) : fn(f) {}
    HttpResult invoke(DzScriptServerPane* pane) override { return fn(pane); }
    Fn fn;
};

// Drop one reference; deletes the call on the last one.
void release(Call* call);

// MAIN THREAD ONLY (DzScriptServerPane::handleMainThreadCall). Claims and runs
// the call unless the worker already abandoned it, then drops the main
// thread's reference. An exception from invoke() becomes a 500
// INTERNAL_ERROR result; the waiting worker is always released.
void runOnMainThread(DzScriptServerPane* pane, Call* call);

// MAIN THREAD ONLY. Marks a server script as running for its lifetime
// (daz-script-server-29gd). A script that pumps the event loop -- Iray's
// DzProgress does -- would otherwise let runOnMainThread() start a queued
// call inside it, and a nested DzScript::execute deadlocks on a lock the
// outer one holds. While any ScriptScope is alive, runOnMainThread() holds
// calls back instead and re-posts them when the outermost scope ends.
class ScriptScope {
public:
    ScriptScope();
    ~ScriptScope();
private:
    ScriptScope(const ScriptScope&);
    ScriptScope& operator=(const ScriptScope&);
};

// MAIN THREAD ONLY. True while a ScriptScope is alive.
bool scriptRunning();

enum Outcome { Completed, GaveUp, PostFailed };

// WORKER THREAD. Takes ownership of call (both references). Posts it to the
// pane's thread and waits. Returns Completed with *out set, GaveUp if the
// client disconnected or queueTimeoutMs passed before the main thread started
// the call (it will never run), or PostFailed if it could not be posted.
// queueTimeoutMs bounds only the wait to *start*; a running call is waited for.
Outcome post(DzScriptServerPane* pane, Call* call, int queueTimeoutMs,
             const std::function<bool()>& isClientGone, HttpResult* out);

} // namespace MainThreadCall

struct HttpContext;

// WORKER THREAD. The one way an HTTP handler runs code on the main thread
// (yau7.2.1). Answers ctx in every case: 503 STUDIO_BUSY when Studio is busy
// (if checkBusy) or the call isn't started within queueTimeoutSec (it then
// never runs), 500 INTERNAL_ERROR when it can't be posted, throws, or returns
// a status outside 100-599; otherwise fn's result. Defined in RequestHandlers.cpp.
void callOnMainThread(DzScriptServerPane* pane, HttpContext& ctx, int queueTimeoutSec,
                      const MainThreadCall::FunctionCall::Fn& fn, bool checkBusy = true);
