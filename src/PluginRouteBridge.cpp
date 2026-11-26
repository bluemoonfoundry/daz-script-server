// DzScriptServerPane: companion-plugin registration and the catch-all routes
// that dispatch to plugin slots (applyPluginRoutes).
#include "PaneInternal.h"
#include "PluginRouteSelfTest.h"

// ─── Plugin Route Registration ────────────────────────────────────────────────

// Keep the busy-time /capabilities snapshot current after the registry
// changes. buildCapabilitiesJson() reads GUI-owned settings, so only refresh
// on the main thread (companion plugins register through a blocking queued
// call, which lands here); otherwise the next live request refreshes it.
void DzScriptServerPane::refreshCapabilitiesIfRunning()
{
	if (m_bRunning && QThread::currentThread() == thread())
		refreshCapabilitiesSnapshot();
}

bool DzScriptServerPane::registerCompanionPlugin(const QString& name, const QString& version,
                                                 const QString& description)
{
	if (!m_pluginRegistry.registerCompanion(name, version, description)) {
		appendLog(QString("[WARNING] Companion plugin registration rejected: invalid name or "
		                  "version (%1 %2)").arg(name.left(80), version.left(80)));
		return false;
	}
	appendLog(QString("[INFO] Companion plugin registered: %1 %2").arg(name, version));
	refreshCapabilitiesIfRunning();
	return true;
}

void DzScriptServerPane::unregisterCompanionPlugin(const QString& name)
{
	m_pluginRegistry.unregisterCompanion(name);
	refreshCapabilitiesIfRunning();
}

bool DzScriptServerPane::registerPluginRoute(const QString& method, const QString& path,
                                              QObject* receiver, const QString& slotName)
{
	return registerPluginRouteImpl(method, path, receiver, slotName, QString());
}

bool DzScriptServerPane::registerPluginRoute(const QString& method, const QString& path,
                                              QObject* receiver, const QString& slotName,
                                              const QString& pluginName)
{
	if (!PluginRouteRegistry::isValidName(pluginName))
		return false;
	return registerPluginRouteImpl(method, path, receiver, slotName, pluginName);
}

bool DzScriptServerPane::registerPluginRouteImpl(const QString& method, const QString& path,
                                                  QObject* receiver, const QString& slotName,
                                                  const QString& pluginName)
{
	QString m;
	if (!m_pluginRegistry.registerRoute(method, path, receiver, slotName, pluginName, &m))
		return false;
	appendLog(pluginName.isEmpty()
		? QString("[INFO] Plugin route registered: %1 %2").arg(m).arg(path)
		: QString("[INFO] Plugin route registered: %1 %2 (%3)").arg(m, path, pluginName));
	refreshCapabilitiesIfRunning();
	return true;
}

void DzScriptServerPane::unregisterPluginRoute(const QString& method, const QString& path)
{
	m_pluginRegistry.unregisterRoute(method, path);
	refreshCapabilitiesIfRunning();
}

// ─── Built-in self-test routes (ih7u) ────────────────────────────────────────

namespace {
struct SelfTestRoute { const char* method; const char* path; const char* slot; };
// "gone" is registered against a receiver deleted right after, so its
// QPointer reads null at dispatch; "noslot" names a slot the receiver lacks.
const SelfTestRoute kSelfTestRoutes[] = {
	{ "GET",  "/_selftest/plugin-route/:id",    "echo"       },
	{ "POST", "/_selftest/plugin-route",        "echo"       },
	{ "PUT",  "/_selftest/plugin-route/:id",    "echo"       },
	{ "GET",  "/_selftest/plugin-route-bad",    "badStatus"  },
	{ "GET",  "/_selftest/plugin-route-noslot", "noSuchSlot" },
};
const char kSelfTestGonePath[] = "/_selftest/plugin-route-gone";
} // namespace

bool DzScriptServerPane::setPluginRouteSelfTest(bool enabled)
{
	for (const SelfTestRoute& r : kSelfTestRoutes)
		m_pluginRegistry.unregisterRoute(r.method, r.path);
	m_pluginRegistry.unregisterRoute("GET", kSelfTestGonePath);
	delete m_pRouteSelfTest.data();  // QPointer: no-op when null

	bool ok = true;
	if (enabled) {
		m_pRouteSelfTest = new PluginRouteSelfTest(this);
		// The same public entry point a companion plugin calls.
		for (const SelfTestRoute& r : kSelfTestRoutes)
			ok = registerPluginRoute(r.method, r.path, m_pRouteSelfTest.data(), r.slot) && ok;
		QObject* gone = new PluginRouteSelfTest(this);
		ok = registerPluginRoute("GET", kSelfTestGonePath, gone, "echo") && ok;
		delete gone;
	}
	appendLog(QString("[INFO] Plugin route self-test %1").arg(enabled ? "enabled" : "disabled"));
	refreshCapabilitiesIfRunning();
	return ok;
}

void DzScriptServerPane::applyPluginRoutes()
{
	// Register a single catch-all handler per HTTP method.  Each handler scans
	// m_pluginRegistry at request time (mutex-protected) so that routes registered
	// after server start — and routes that change dynamically — are always
	// visible without ever touching httplib's handler vectors post-startup.
	// This avoids the data race that would occur if we called m_pServer->Get/Post
	// from registerPluginRoute() while the listen thread is dispatching requests.

	auto makeHandler = [this](const QString& method) {
		return [this, method](const httplib::Request& req, httplib::Response& res) {
			const QString qpath = QString::fromStdString(req.path);
			QMap<QString, QString> params;

			QPointer<QObject> receiver;
			QByteArray        slotBytes;
			const bool found = m_pluginRegistry.match(method, qpath, &receiver, &slotBytes, &params);

			if (!found) {
				res.status = 404;
				res.set_content(ErrorResponse::build(ErrorCode::ROUTE_NOT_FOUND, req.method + " " + req.path),
				                "application/json");
				return;
			}

			// Plugin routes get the same checks as built-in ones: GET uses the
			// read chain (IP whitelist + auth), every other method the write
			// chain (IP whitelist + rate limit + body size + auth). Runs after
			// matching so unknown paths still return 404 rather than 401.
			{
				auto ctx = toContext(req);
				const MiddlewareChain& chain =
					(method == "GET") ? *m_pReadChain : *m_pWriteChain;
				if (!chain.run(ctx)) {
					applyContext(ctx, res);
					return;
				}
			}

			// Wrap path params + body into a single JSON envelope so the slot can
			// access both without a separate signature.
			// The envelope is QByteArray (Qt CRT) to avoid a heap mismatch between
			// Qt's msvcr100 and DazScriptServer's ucrtbase; the params go through
			// variantToJsonBytes so a '"' or '\' in a path segment stays valid
			// JSON (W10).
			QByteArray body;
			if (!params.isEmpty()) {
				QVariantMap paramMap;
				for (auto it = params.begin(); it != params.end(); ++it)
					paramMap.insert(it.key(), it.value());
				const QByteArray paramsJson = JsonStd::variantToJsonBytes(paramMap);
				QByteArray rawBody(req.body.c_str(), (int)req.body.size());
				body = "{\"_pathParams\":" + paramsJson + ",\"_body\":" +
				       (rawBody.isEmpty() ? QByteArray("null") : rawBody) + "}";
			} else {
				body = stdToQBA(req.body);
			}

			QByteArray ip(req.remote_addr.c_str(), (int)req.remote_addr.size());
			// Busy check, bounded wait, and the receiver check all happen in
			// the shared main-thread crossing (yau7.2.1).
			HttpContext ctx = toContext(req);
			callPluginRouteOnMainThread(this, ctx, mainThreadQueueTimeoutSec(), receiver, slotBytes, body, ip);
			applyContext(ctx, res);
		};
	};

	// The catch-alls must be registered AFTER all specific routes so httplib
	// matches specific paths first (httplib tries handlers in registration order).
	m_pServer->Get   ("/(.*)", makeHandler("GET"));
	m_pServer->Post  ("/(.*)", makeHandler("POST"));
	m_pServer->Put   ("/(.*)", makeHandler("PUT"));
	m_pServer->Delete("/(.*)", makeHandler("DELETE"));
	m_pServer->Patch ("/(.*)", makeHandler("PATCH"));
}
