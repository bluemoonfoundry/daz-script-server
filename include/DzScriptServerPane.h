#pragma once
#include <memory>
#include <atomic>
#include <functional>
#include <string>
#include <utility>
#include <dzpane.h>
#include <QtCore/qpair.h>
#include <QtCore/qthread.h>
#include <QtCore/qstringlist.h>
#include <QtCore/qvariant.h>
#include <QtCore/qbytearray.h>
#include <QtCore/qatomic.h>
#include <QtCore/qmutex.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qtimer.h>
#include <QtCore/qmetatype.h>
#include <QtCore/qpointer.h>
#if DAZ_SDK_MAJOR_VERSION >= 6
// These widget classes moved from QtGui to QtWidgets in Qt5/6.
#include <QtWidgets/qspinbox.h>
#include <QtWidgets/qlineedit.h>
#include <QtWidgets/qpushbutton.h>
#include <QtWidgets/qlabel.h>
#include <QtWidgets/qtextedit.h>
#include <QtWidgets/qcheckbox.h>
#include <QtWidgets/qgroupbox.h>
#else
#include <QtGui/qspinbox.h>
#include <QtGui/qlineedit.h>
#include <QtGui/qpushbutton.h>
#include <QtGui/qlabel.h>
#include <QtGui/qtextedit.h>
#include <QtGui/qcheckbox.h>
#include <QtGui/qgroupbox.h>
#endif

#include "AuthenticationService.h"
#include "RateLimiterService.h"
#include "IPWhitelistService.h"
#include "ArtifactRoots.h"
#include "ScriptRegistry.h"
#include "PluginRouteRegistry.h"
#include "MetricsCollector.h"
#include "RequestHandler.h"
#include "AsyncRequestManager.h"
#include "IdempotencyCache.h"
#include "SettingsService.h"
#include "ServerSettings.h"
#include "ServerConfig.h"
#include "SceneEventBroker.h"
#include "RenderProgressBroker.h"
#include "ArtifactThumbnail.h"

// Metatype needed to pass HttpResult through queued calls.
typedef QPair<int, QByteArray> HttpResult;
Q_DECLARE_METATYPE(HttpResult)

// Forward-declare httplib::Server — httplib.h included only in DzScriptServerPane.cpp
namespace httplib { class Server; struct Request; struct Response; }

class DzScript;
class GeometryFramesHandler;  // fork: GeometryExport.h

class DzScriptServerPane : public DzPane {
	Q_OBJECT
	Q_PROPERTY(int     nPort    READ getPort    WRITE setPort)
	Q_PROPERTY(QString sHost    READ getHost    WRITE setHost)
	Q_PROPERTY(bool    bRunning READ isRunning)

public:
	DzScriptServerPane();
	~DzScriptServerPane();

	Q_INVOKABLE int     getPort()  const { return m_nPort; }
	Q_INVOKABLE void    setPort(int p)   { m_nPort = p; }
	Q_INVOKABLE QString getHost()  const { return m_sHost; }
	Q_INVOKABLE void    setHost(const QString& h) { m_sHost = h; }
	Q_INVOKABLE bool    isRunning() const { return m_bRunning.load(); }

	// Plugin route registration — called by companion plugins loaded in the same process.
	// Registers method+path on the httplib server immediately (or at next server start if
	// the server is not yet running).
	// receiver must expose slotName as Q_INVOKABLE with signature HttpResult(QByteArray,QByteArray).
	Q_INVOKABLE bool registerPluginRoute(const QString& method, const QString& path,
	                                     QObject* receiver, const QString& slotName);
	// Same, attributing the route to a companion plugin (see
	// registerCompanionPlugin). A plugin name not yet registered is added
	// with no version. Returns false (and registers nothing) if pluginName is
	// not a valid plugin name.
	Q_INVOKABLE bool registerPluginRoute(const QString& method, const QString& path,
	                                     QObject* receiver, const QString& slotName,
	                                     const QString& pluginName);
	Q_INVOKABLE void unregisterPluginRoute(const QString& method, const QString& path);

	// Companion-plugin discovery registry, listed in GET /capabilities under
	// "companion_plugins" with each plugin's routes. name: 1-64 chars of
	// [A-Za-z0-9._-] (e.g. "daz-bridge-usd"); version: 1-64 printable chars.
	// Re-registering a name updates its version/description. Returns false on
	// an invalid name or version.
	Q_INVOKABLE bool registerCompanionPlugin(const QString& name, const QString& version,
	                                         const QString& description);
	// Removes the plugin and every route attributed to it.
	Q_INVOKABLE void unregisterCompanionPlugin(const QString& name);

public slots:
	Q_INVOKABLE void startServer();
	Q_INVOKABLE void stopServer();

	// Called on the main thread through callOnMainThread() from httplib handler threads.
	// Returns HttpResult (status, jsonBody) so handlers can set the correct HTTP status code.
	Q_INVOKABLE HttpResult handleExecuteRequest(const QByteArray& jsonBody, const QByteArray& clientIP, qint64 acceptedAtMs);
	Q_INVOKABLE HttpResult handleRegisterScript(const QByteArray& jsonBody, const QByteArray& clientIP);
	Q_INVOKABLE HttpResult handleRegistryExecuteRequest(const QByteArray& scriptText, const QByteArray& scriptId, const QByteArray& requestBody, const QByteArray& clientIP);

	// On Studio 6 these are called directly from HTTP workers and use only local,
	// reentrant Qt Core values plus mutex-protected services. Studio 4 routes them
	// through callOnMainThread() because its JSON parser uses QScriptEngine.
	// Neither path touches GUI, DzScript, or DAZ SDK state off the main thread.
	// The script limit is an immutable snapshot captured before server start.
	// correlationId is the job route's resolved X-Correlation-Id, stored on the job.
	Q_INVOKABLE HttpResult handleAsyncExecuteEnqueue(const QByteArray& jsonBody,
	                                                const QByteArray& clientIP,
	                                                int maxScriptLengthKB,
	                                                const QByteArray& correlationId);
	Q_INVOKABLE HttpResult handleAsyncScriptEnqueue(const QByteArray& scriptBytes,
	                                                const QByteArray& scriptIdBytes,
	                                                const QByteArray& bodyBytes,
	                                                const QByteArray& correlationId);

	// Render enqueue still builds Daz/Qt render work on the main thread.
	Q_INVOKABLE HttpResult handleAsyncRenderEnqueue(const QByteArray& jsonBody,
	                                               const QByteArray& correlationId);
	Q_INVOKABLE HttpResult handleAsyncRenderBatchEnqueue(const QByteArray& jsonBody,
	                                                    const QByteArray& correlationId);
	Q_INVOKABLE HttpResult handleAsyncRenderAnimationEnqueue(const QByteArray& jsonBody,
	                                                        const QByteArray& correlationId);

	// Scene I/O helpers — called on the main thread through callOnMainThread().
	Q_INVOKABLE HttpResult handleSaveCopy(const QByteArray& jsonBody);

	// GET /capabilities — main thread (reads render engines live from DzRenderMgr).
	// Also refreshes the snapshot served while the main thread is busy.
	Q_INVOKABLE HttpResult handleCapabilitiesRequest();

	// GET /artifacts/{id}/{artifact_id}?thumbnail=<px> — main thread. job is an
	// ArtifactThumbnail::Job* posted with Qt::QueuedConnection by the HTTP worker,
	// which waits on job->done with a timeout (see serveArtifactThumbnail()).
	Q_INVOKABLE void handleThumbnailJob(qulonglong job);

	// Sync /execute and /scripts/:id/execute — main thread. call is a
	// MainThreadCall::Call* posted with Qt::QueuedConnection by the HTTP worker,
	// which gives up if it is not started in time (see MainThreadCall.h).
	Q_INVOKABLE void handleMainThreadCall(qulonglong call);

	void appendLog(const QString& line);
	// Worker-thread-safe: accepts log data as QByteArray (whose ~QByteArray calls qFree,
	// not ::free, so it is safe to construct/destroy on httplib worker threads).
	void appendLogBytes(const QByteArray& data);
	void updateActiveRequestsLabel();
	void updateEventClientsLabel();

public:
	// Observability — called from HTTP threads (thread-safe; no Qt string ops on worker threads)
	std::string getHealthJson() const;
	std::string getMetricsJson() const;

	// Main-thread busy state — called from HTTP threads (lock-free atomic read via SceneEventBroker)
	bool        isMainThreadBusy() const;
	// How long a worker waits for the main thread to start its call before
	// answering 503 (the request timeout; fixed while the server runs).
	int         mainThreadQueueTimeoutSec() const { return m_nTimeoutSec; }
	std::string mainThreadBusyMessage() const;

	// Last capabilities document built on the main thread, with render engines
	// marked source "snapshot". Served by GET /capabilities while the main thread
	// is busy. Mutex-protected; empty until the server has started.
	QByteArray  capabilitiesSnapshot() const;

	// Identity of this server run: a fresh random ID on every startServer(),
	// so clients can tell a restart (and the loss of in-memory jobs and
	// idempotency records) from a slow response. Written on the main thread
	// before the listen thread starts; read-only while the server runs.
	QByteArray  serverInstanceId() const { return m_serverInstanceId; }

	// Monotonic counter, reset on each server start, bumped on every structural
	// scene change (SceneEventBroker) and after every executed script or job
	// (scripts may mutate anything). Equal values => no observed change.
	int         sceneRevision() const { return m_sceneRevision.fetchAndAddOrdered(0); }

	// Script Registry operations — called from HTTP threads (mutex-protected, no Qt string ops)
	std::string                 listScriptsJson() const;
	std::pair<int, std::string> deleteRegistryScriptJson(const std::string& id, const std::string& clientIP);
	bool                        lookupRegistryScript(const std::string& id, std::string& outScript) const;

	// Async request management — called from HTTP threads (delegated to AsyncRequestManager)
	// Qt value types here are protected by AsyncRequestManager's mutex and are
	// only called directly from documented reentrant Studio 6 worker paths.
	QString              enqueueAsyncRequest(const QString& scriptText, const QString& scriptFile,
	                                         const QString& reportFile, const QVariantMap& args,
	                                         const QString& idPrefix, const QString& correlationId,
	                                         qint64& outSubmittedAt, QString& outError);
	std::pair<int, std::string> getAsyncStatusJson(const std::string& requestId);
	std::pair<int, std::string> getAsyncResultJson(const std::string& requestId, bool doWait, int timeoutSec,
	                                               const std::function<bool()>& isClientGone);
	std::pair<int, std::string> cancelAsyncRequestJson(const std::string& requestId, const std::string& clientIP);
	std::pair<int, std::string> cancelRenderRequestJson(const std::string& requestId, const std::string& clientIP);
	std::string                 listAsyncRequestsJson(const std::string& statusFilter);

private slots:
	// MAIN THREAD: samples DzProgress/DzBackgroundProgress into m_progressBusy.
	void pollProgressBusy();
	void onStartClicked();
	void onStopClicked();
	void onMessagePosted(const QString& msg);
	void onCopyTokenClicked();
	void onRegenTokenClicked();
	void onAuthEnabledChanged(int state);
	void onClearLogClicked();
	void onIpWhitelistEnabledChanged(int state);
	void onArtifactRootsEnabledChanged(int state);
	void onRateLimitEnabledChanged(int state);
	void onAutoStartChanged(int state);
	void onStaleTimeoutChanged(int minutes);

	// Async execution (runs on main thread via Qt event loop)
	void processNextAsyncRequest();
	void cleanupExpiredRequests();
	void killRenderOnMainThread();

private:
	// Stops brokers and the HTTP server, joins the listen thread (pumping
	// non-input events so blocked main-thread calls can finish), then frees
	// thread, server and brokers. On join timeout they are leaked, never
	// terminate()d. Used by stopServer() and by a failed bind in startServer().
	void teardownServer();

	void   setupRoutes();
	// Job routes (execute, async submit, render submit): write chain, then
	// X-Correlation-Id / Idempotency-Key handling, then the handler, then the
	// identity stamp (server_instance_id, correlation_id, scene_revision).
	void   runJobRoute(const httplib::Request& req, httplib::Response& res,
	                   IRequestHandler* handler, bool idempotent);
	void   applyPluginRoutes();
	// HTTP worker: GET /artifacts/:job_id/:artifact_id?thumbnail=<px>[&format=].
	// Decoding happens on the main thread via handleThumbnailJob().
	void   serveArtifactThumbnail(const httplib::Request& req, httplib::Response& res);
	void   updateUI();
	DzScript* ensurePersistentScript();
	void      endProgressOfCancelledRender(const QString& requestId);

	// One script run on the persistent DzScript with print() output captured
	// (yau7.5.1). Loads scriptFile when set, else runs scriptText. MAIN THREAD.
	struct CapturedScriptRun {
		bool        loaded;    // false: scriptFile could not be loaded (not run)
		bool        success;
		QVariant    result;
		QStringList output;
		QString     error;     // "Line N: message" when the line is known
		CapturedScriptRun() : loaded(true), success(false) {}
	};
	CapturedScriptRun runCapturedScript(const QString& scriptFile, const QString& scriptText,
	                                    const QVariantMap& args);
	QString buildResponseJson(bool success,
	                          const QVariant& result,
	                          const QStringList& output,
	                          const QVariant& error,
	                          const QString& requestId = QString());

	void    loadSettings();
	void    saveSettings();
	void    applySettings(const ServerSettings& s);
	QByteArray  buildCapabilitiesJson(const QString& engineSource) const;   // main thread only
	void        refreshCapabilitiesSnapshot();

	// Server state
	httplib::Server* m_pServer;
	QThread*         m_pServerThread;   // actually a ServerListenThread*
	int              m_nPort;
	QString          m_sHost;
	QByteArray       m_aHostUtf8;
	// Written on the main thread, read by HTTP workers (GET /health).
	std::atomic<bool> m_bRunning;
	int              m_nTimeoutSec;
	bool             m_bAutoStart;

	// Configurable limits
	int              m_nMaxConcurrentRequests;
	int              m_nMaxBodySizeMB;
	int              m_nMaxScriptLengthKB;
	int              m_nStaleJobTimeoutMin;   // main thread only; applied live

	// Log capture during script execution
	QStringList m_aCapturedLogLines;
	bool        m_bCapturingLog;

	// Non-empty only while processNextAsyncRequest() is running a render
	// request (id starting "rnd-"). onMessagePosted() checks this to scan
	// captured lines for [DAZPY_FRAME] n/total markers (emitted by
	// buildAnimationRenderScript's per-frame loop) and forward them to
	// m_pRenderProgress/m_pAsyncMgr as progress updates.
	QString     m_sCurrentRenderId;

	// Persistent DzScript instance, reused (via clear()) across every script
	// execution instead of constructing/destroying one per request. All
	// execution is serialized onto this (the main) thread — synchronously for
	// sync requests and by a queued wake-up for async requests — so reuse is
	// sequential, not concurrent. See runDazScript() in the .cpp.
	DzScript* m_pPersistentScript;

	// ── Settings service ─────────────────────────────────────────────────────
	SettingsService       m_settingsService;

	// ── Service objects ───────────────────────────────────────────────────────
	AuthenticationService m_auth;
	RateLimiterService    m_rateLimiter;
	IPWhitelistService    m_ipWhitelist;
	ArtifactRoots         m_artifactRoots;   // GET /artifacts trust boundary
	MetricsCollector      m_metrics;

	QAtomicInt       m_nActiveRequests;  // Current concurrent requests (atomic: written from HTTP threads)

	// Script Registry (session-only, in-memory; see ScriptRegistry.h)
	ScriptRegistry m_scriptRegistry;

	// ── Async Request Infrastructure ─────────────────────────────────────────
	//
	// THREADING MODEL:
	//   HTTP threads: call enqueueAsyncRequest() / getAsyncStatusJson() / etc.,
	//                 which delegate to AsyncRequestManager (mutex-protected).
	//   Main thread:  processNextAsyncRequest() dequeues and executes serially.
	//                 All DzScript execution happens here, same as sync path.
	//
	// IMPORTANT: processNextAsyncRequest() blocks the main thread (and thus the
	// Qt event loop) for the full duration of each script execution.  That is
	// intentional — DAZ Studio's API is single-threaded.  Status queries are
	// served directly from AsyncRequestManager's mutex-protected map without
	// needing the main thread, so polling always returns promptly.

	// Plugin route registry — populated by companion plugins via registerPluginRoute()
	// and registerCompanionPlugin(); matched by the catch-alls applyPluginRoutes()
	// installs. See PluginRouteRegistry.h.
	PluginRouteRegistry m_pluginRegistry;
	void refreshCapabilitiesIfRunning();
	bool registerPluginRouteImpl(const QString& method, const QString& path,
	                             QObject* receiver, const QString& slotName,
	                             const QString& pluginName);

	QByteArray         m_serverInstanceId;       // see serverInstanceId()
	mutable QAtomicInt m_sceneRevision;          // see sceneRevision()
	IdempotencyCache   m_idempotency;            // Idempotency-Key replay records (cleared per run)

	QByteArray         m_capabilitiesSnapshot;   // see capabilitiesSnapshot()
	// Image extensions Qt can decode, read on the main thread before the HTTP
	// server starts and read-only while it runs (thumbnail_supported, 422s).
	QStringList        m_thumbnailExtensions;
	ArtifactThumbnail::Cache m_thumbnailCache;   // encoded thumbnails, LRU, mutex-protected
	mutable QMutex     m_capabilitiesMutex;

	AsyncRequestManager*  m_pAsyncMgr;
	QTimer*               m_pCleanupTimer;    // Fires every 5 min to purge TTL-expired requests
	// DzProgress state for HTTP workers (yau7.2.3): DzProgress APIs are
	// main-thread only, so a timer samples them; workers read only this.
	enum ProgressBusy { ProgressIdle = 0, ProgressForeground = 1, ProgressBackground = 2 };
	QTimer*               m_pProgressPollTimer;
	std::atomic<int>      m_progressBusy;
	SceneEventBroker*     m_pEventBroker;     // SSE scene-change notification broker
	RenderProgressBroker* m_pRenderProgress;  // SSE render progress notification broker

	// ── Middleware chains (created in setupRoutes) ────────────────────────────
	// Every authenticated route uses exactly one of these two chains, so the IP
	// whitelist always runs before auth (tests/test_route_security.py checks this).
	std::unique_ptr<MiddlewareChain> m_pWriteChain;  // IP + rate + body_size + auth (POST/DELETE)
	std::unique_ptr<MiddlewareChain> m_pReadChain;   // IP + auth (GET polling / SSE streams)

	// ── Request handlers (created in setupRoutes) ─────────────────────────────
	std::unique_ptr<StatusHandler>        m_pStatusHandler;
	std::unique_ptr<HealthHandler>        m_pHealthHandler;
	std::unique_ptr<MetricsHandler>       m_pMetricsHandler;
	std::unique_ptr<CapabilitiesHandler>  m_pCapabilitiesHandler;
	std::unique_ptr<ExecuteScriptHandler> m_pExecuteHandler;
	std::unique_ptr<ScriptRegisterHandler> m_pRegisterHandler;
	std::unique_ptr<ScriptListHandler>    m_pScriptListHandler;
	std::unique_ptr<ScriptDeleteHandler>  m_pScriptDeleteHandler;
	std::unique_ptr<ScriptExecuteHandler> m_pScriptExecHandler;
	std::unique_ptr<AsyncExecuteHandler>  m_pAsyncExecHandler;
	std::unique_ptr<AsyncScriptHandler>   m_pAsyncScriptHandler;
	std::unique_ptr<AsyncStatusHandler>   m_pAsyncStatusHandler;
	std::unique_ptr<AsyncResultHandler>   m_pAsyncResultHandler;
	std::unique_ptr<AsyncCancelHandler>   m_pAsyncCancelHandler;
	std::unique_ptr<AsyncListHandler>     m_pAsyncListHandler;
	std::unique_ptr<RenderHandler>          m_pRenderHandler;
	std::unique_ptr<RenderBatchHandler>     m_pRenderBatchHandler;
	std::unique_ptr<RenderAnimationHandler> m_pRenderAnimationHandler;
	std::unique_ptr<RenderCancelHandler>    m_pRenderCancelHandler;
	std::unique_ptr<SaveCopyHandler>      m_pSaveCopyHandler;
	std::unique_ptr<GeometryFramesHandler> m_pGeometryFramesHandler;  // fork: GeometryExport.h

	// UI widgets
	QLineEdit*   m_pHostEdit;
	QSpinBox*    m_pPortSpin;
	QSpinBox*    m_pTimeoutSpin;
	QPushButton* m_pStartBtn;
	QPushButton* m_pStopBtn;
	QLabel*      m_pStatusLabel;
	QLabel*      m_pActiveRequestsLabel;
	QLabel*      m_pEventClientsLabel;
	QTextEdit*   m_pLogView;
	QPushButton* m_pClearLogBtn;

	// Authentication UI
	QCheckBox*   m_pAuthEnabledCheck;
	QLineEdit*   m_pTokenEdit;
	QPushButton* m_pCopyTokenBtn;
	QPushButton* m_pRegenTokenBtn;
	QCheckBox*   m_pAutoStartCheck;

	// IP Whitelist UI
	QCheckBox*   m_pIpWhitelistCheck;
	QLineEdit*   m_pIpWhitelistEdit;

	// Artifact roots UI
	QCheckBox*   m_pArtifactRootsCheck;
	QLineEdit*   m_pArtifactRootsEdit;

	// Rate Limiting UI
	QCheckBox*   m_pRateLimitCheck;
	QSpinBox*    m_pRateLimitMaxSpin;
	QSpinBox*    m_pRateLimitWindowSpin;

	// Advanced Limits UI
	QSpinBox*    m_pMaxConcurrentSpin;
	QSpinBox*    m_pMaxBodySizeSpin;
	QSpinBox*    m_pMaxScriptLengthSpin;
	QSpinBox*    m_pStaleTimeoutSpin;
};
