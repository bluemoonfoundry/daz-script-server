#pragma once
// Builds the GET /capabilities document (routes, companion plugins, features,
// limits, security settings, render engines, compatibility hash).
//
// THREADING: main thread only. It reads DzRenderMgr; the pane gathers its
// GUI-owned settings into Inputs there and serves the result to worker
// threads as a snapshot (DzScriptServerPane::capabilitiesSnapshot()).

#include "PluginRouteRegistry.h"
#include <QtCore/qbytearray.h>
#include <QtCore/qlist.h>
#include <QtCore/qstring.h>
#include <QtCore/qstringlist.h>

namespace Capabilities {

struct Inputs {
    QByteArray serverInstanceId;
    QList<PluginRouteRegistry::Route>     pluginRoutes;
    QList<PluginRouteRegistry::Companion> companions;

    int  maxBodySizeMB          = 0;
    int  maxScriptLengthKB      = 0;
    int  maxConcurrentRequests  = 0;
    int  asyncMaxQueueDepth     = 0;
    int  idempotencyTtlSeconds  = 0;
    int  staleJobTimeoutMin     = 0;
    QStringList thumbnailExtensions;

    bool rateLimitEnabled       = false;
    int  rateLimitMax           = 0;
    int  rateLimitWindowSeconds = 0;

    bool authEnabled            = true;
    bool ipWhitelistEnabled     = false;
    bool artifactRootsEnabled   = true;
    QStringList artifactRoots;
};

// engineSource: "live" for a request served on the main thread, "snapshot"
// for the cached copy served while Studio is busy.
QByteArray build(const Inputs& in, const QString& engineSource);

} // namespace Capabilities
