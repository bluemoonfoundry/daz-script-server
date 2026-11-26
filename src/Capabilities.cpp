// GET /capabilities document. Split out of DzScriptServerPane.cpp (x7ul.32);
// see Capabilities.h.
#include "Capabilities.h"
#include "ServerConfig.h"
#include "JsonBuilder.h"
#include "ArtifactThumbnail.h"
#include "common_version.h"

#include <dzapp.h>
#include <dzrendermgr.h>
#include <dzrenderer.h>

#include <QtCore/qcryptographichash.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qmetaobject.h>
#include <QtCore/qvariant.h>

namespace {

// Core route table reported by GET /capabilities. Paths use OpenAPI-style
// {id} placeholders for the ([^/]+) captures in setupRoutes().
// tests/test_route_security.py fails if this table and setupRoutes() drift apart.
struct CapabilityRoute {
	const char* method;
	const char* path;
	bool        auth;     // false only for the deliberately public routes
	const char* kind;     // "json" | "sse" | "binary"
};

const CapabilityRoute kCapabilityRoutes[] = {
	{ "GET",    "/status",                 false, "json"   },
	{ "GET",    "/health",                 false, "json"   },
	{ "GET",    "/metrics",                false, "json"   },
	{ "GET",    "/capabilities",           true,  "json"   },
	{ "POST",   "/execute",                true,  "json"   },
	{ "POST",   "/scripts/register",       true,  "json"   },
	{ "GET",    "/scripts",                true,  "json"   },
	{ "DELETE", "/scripts/{id}",           true,  "json"   },
	{ "POST",   "/scripts/{id}/execute",   true,  "json"   },
	{ "POST",   "/execute/async",          true,  "json"   },
	{ "POST",   "/scripts/{id}/async",     true,  "json"   },
	{ "GET",    "/requests/{id}/status",   true,  "json"   },
	{ "GET",    "/requests/{id}/result",   true,  "json"   },
	{ "DELETE", "/requests/{id}",          true,  "json"   },
	{ "GET",    "/requests",               true,  "json"   },
	{ "GET",    "/artifacts/{id}",         true,  "json"   },
	{ "GET",    "/artifacts/{id}/{artifact_id}", true, "binary" },
	{ "POST",   "/render",                 true,  "json"   },
	{ "POST",   "/render/batch",           true,  "json"   },
	{ "POST",   "/render/animation",       true,  "json"   },
	{ "POST",   "/render/{id}/cancel",     true,  "json"   },
	{ "POST",   "/scene/save-copy",        true,  "json"   },
	{ "POST",   "/geometry/frames",        true,  "binary" },
	{ "GET",    "/scene/events",           true,  "sse"    },
	{ "GET",    "/render/{id}/progress",   true,  "sse"    },
};

// Engines POST /render accepts in its "engine" field, and the renderer class
// each one needs (null = no renderer lookup; viewport uses a ScreenShot render).
struct SelectableEngine {
	const char* engine;
	const char* rendererClass;
};

const SelectableEngine kSelectableEngines[] = {
	{ "viewport", nullptr },
	{ "iray",     "DzIrayRenderer" },
	{ "filament", "DzFilamentRenderer" },
};

} // namespace

QByteArray Capabilities::build(const Inputs& in, const QString& engineSource)
{
	// Main thread only: reads GUI-owned settings and DzRenderMgr.
	//
	// Written straight to JSON on purpose. A QVariantList built here allocates
	// its QVariant* nodes with this DLL's CRT (ucrtbase); stored inside a
	// QVariant/QVariantMap, the last reference is released by QtCore's
	// ~QVariant, which frees them with Qt's CRT (msvcr100 on DAZ Studio 4)
	// -> heap corruption on startup. QVariantMap and QStringList are safe
	// (their storage is allocated and freed inside QtCore), so arrays here
	// are emitted item by item and never wrapped in a QVariant.
	JsonBuilder json;
	json.startObject();
	json.addMember("schema_version", ServerConfig::CAPABILITIES_SCHEMA_VERSION);

	QVariantMap server;
	server["name"]    = QString("DazScriptServer");
	server["version"] = QString(DZSRV_VERSION_STR);
	server["instance_id"] = QString::fromLatin1(in.serverInstanceId);
	json.addMember("server", QVariant(server));

	QVariantMap studio;
	studio["version"]          = dzApp ? dzApp->getVersionString() : QString();
	studio["sdk_version"]      = QString("%1.%2.%3.%4")
		.arg(DZ_SDK_VERSION_MAJOR).arg(DZ_SDK_VERSION_MINOR)
		.arg(DZ_SDK_VERSION_REV).arg(DZ_SDK_VERSION_BUILD);
	studio["sdk_major"]        = DZ_SDK_VERSION_MAJOR;
	studio["qt_version"]       = QString(qVersion());
	studio["qt_build_version"] = QString(QT_VERSION_STR);
	json.addMember("studio", QVariant(studio));

	// ── Routes ───────────────────────────────────────────────────────────────
	QStringList hashLines;
	json.addKey("routes");
	json.startArray();
	for (size_t i = 0; i < sizeof(kCapabilityRoutes) / sizeof(kCapabilityRoutes[0]); ++i) {
		const CapabilityRoute& r = kCapabilityRoutes[i];
		QVariantMap m;
		m["method"] = QString(r.method);
		m["path"]   = QString(r.path);
		m["auth"]   = r.auth;
		m["kind"]   = QString(r.kind);
		json.addItem(QVariant(m));
		hashLines << QString("route %1 %2").arg(QString(r.method), QString(r.path));
	}
	json.finishArray();

	bool hasPluginRoutes = false;
	{
		const QList<PluginRouteRegistry::Route>&     pluginRoutes = in.pluginRoutes;
		const QList<PluginRouteRegistry::Companion>& companions   = in.companions;

		// Flat list, kept for existing clients; companion_plugins below groups it.
		json.addKey("plugin_routes");
		json.startArray();
		for (int i = 0; i < pluginRoutes.size(); ++i) {
			const PluginRouteRegistry::Route& r = pluginRoutes.at(i);
			QVariantMap m;
			m["method"] = r.method;
			m["path"]   = r.path;
			m["auth"]   = true;
			m["owner"]  = r.receiver ? QString(r.receiver->metaObject()->className()) : QString();
			if (!r.plugin.isEmpty()) m["plugin"] = r.plugin;
			json.addItem(QVariant(m));
			hasPluginRoutes = true;
			hashLines << QString("plugin %1 %2").arg(r.method, r.path);
		}
		json.finishArray();

		// Discovery registry: one entry per companion plugin with its routes.
		// Routes registered without a plugin name are grouped by the class of
		// their receiver, with "registered": false and no version. Built with
		// JsonBuilder item by item (no QVariantList; see the CRT note above).
		QStringList groups;      // plugin names, then unattributed owner classes
		QList<bool> registered;
		for (int i = 0; i < companions.size(); ++i) {
			groups << companions.at(i).name;
			registered << true;
			hashLines << QString("companion %1").arg(companions.at(i).name);
		}
		for (int i = 0; i < pluginRoutes.size(); ++i) {
			const PluginRouteRegistry::Route& r = pluginRoutes.at(i);
			if (!r.plugin.isEmpty()) continue;
			const QString owner = r.receiver ? QString(r.receiver->metaObject()->className())
			                                 : QString("unknown");
			bool seen = false;
			for (int g = 0; g < groups.size(); ++g)
				if (!registered.at(g) && groups.at(g) == owner) { seen = true; break; }
			if (!seen) { groups << owner; registered << false; }
		}

		json.addKey("companion_plugins");
		json.startArray();
		for (int g = 0; g < groups.size(); ++g) {
			const bool isRegistered = registered.at(g);
			json.startObjectItem();
			json.addMember("name", groups.at(g));
			json.addMember("registered", isRegistered);
			const PluginRouteRegistry::Companion* info = nullptr;
			if (isRegistered)
				for (int i = 0; i < companions.size(); ++i)
					if (companions.at(i).name == groups.at(g)) { info = &companions.at(i); break; }
			if (info && !info->version.isEmpty()) json.addMember("version", info->version);
			else                                  json.addMemberNull("version");
			if (info && !info->description.isEmpty()) json.addMember("description", info->description);
			json.addKey("routes");
			json.startArray();
			for (int i = 0; i < pluginRoutes.size(); ++i) {
				const PluginRouteRegistry::Route& r = pluginRoutes.at(i);
				bool belongs;
				if (isRegistered) {
					belongs = (r.plugin == groups.at(g));
				} else {
					const QString owner = r.receiver ? QString(r.receiver->metaObject()->className())
					                                 : QString("unknown");
					belongs = r.plugin.isEmpty() && owner == groups.at(g);
				}
				if (!belongs) continue;
				json.startObjectItem();
				json.addMember("method", r.method);
				json.addMember("path", r.path);
				json.addMember("auth", true);
				json.finishObject();
			}
			json.finishArray();
			json.finishObject();
		}
		json.finishArray();
	}

	// ── Feature flags ────────────────────────────────────────────────────────
	QVariantMap features;
	features["async"]               = true;   // /execute/async, /requests/*
	features["async_cancel"]        = true;   // DELETE /requests/{id}
	features["async_long_poll"]     = true;   // /requests/{id}/result?wait=true
	features["report_file"]         = true;   // async "reportFile" JSONL job reports
	features["script_registry"]     = true;   // /scripts/*
	features["sse_scene_events"]    = true;   // /scene/events
	features["sse_render_progress"] = true;   // /render/{id}/progress
	features["render"]              = true;
	features["render_batch"]        = true;
	features["render_animation"]    = true;
	features["render_cancel"]       = true;
	features["scene_save_copy"]     = true;
	features["geometry_frames"]     = true;
	features["companion_plugins"]   = hasPluginRoutes;
	features["idempotency_key"]     = true;   // Idempotency-Key on job submission routes
	features["correlation_id"]      = true;   // X-Correlation-Id echoed on job routes + records
	features["server_instance_id"]  = true;   // per-run identity (X-Server-Instance-Id)
	features["scene_revision"]      = true;   // change counter on /status and job responses
	features["error_envelope"]      = true;   // error_code/error/retryable on every failure
	features["artifacts"]           = true;   // GET /artifacts/{id}[/{artifact_id}] downloads
	features["job_activity"]        = true;   // progress_supported/_source, last_activity_at, idle_ms
	features["animation_frame_progress"] = true; // frame N of M in /render/animation job status
	features["artifact_thumbnails"] = true;   // GET /artifacts/{id}/{artifact_id}?thumbnail=<px>
	json.addMember("features", QVariant(features));
	for (QVariantMap::const_iterator it = features.begin(); it != features.end(); ++it)
		hashLines << QString("feature %1 %2").arg(it.key(), QString(it.value().toBool() ? "1" : "0"));

	// ── Limits (current settings, not just defaults) ─────────────────────────
	QVariantMap limits;
	limits["max_body_size_mb"]        = in.maxBodySizeMB;
	limits["max_script_length_kb"]    = in.maxScriptLengthKB;
	limits["max_concurrent_requests"] = in.maxConcurrentRequests;
	limits["max_batch_variants"]      = ServerConfig::MAX_BATCH_VARIANTS;
	limits["max_animation_frames"]    = ServerConfig::MAX_ANIMATION_FRAMES;
	limits["async_max_queue_depth"]   = in.asyncMaxQueueDepth;
	limits["async_result_ttl_seconds"] = ServerConfig::ASYNC_RESULT_TTL_SEC;
	limits["idempotency_ttl_seconds"]  = in.idempotencyTtlSeconds;
	limits["stale_job_timeout_minutes"] = in.staleJobTimeoutMin;
	limits["thumbnail_min_px"]          = ArtifactThumbnail::kMinPx;
	limits["thumbnail_max_px"]          = ArtifactThumbnail::kMaxPx;
	limits["thumbnail_max_source_mb"]   = int(ArtifactThumbnail::kMaxSourceBytes / (1024 * 1024));
	json.addMember("limits", QVariant(limits));
	// Image types ?thumbnail can decode (Qt image plugins loaded in this
	// Studio). QStringList, not QVariantList: see the DS4 CRT rule.
	json.addMember("thumbnail_source_formats", QVariant(in.thumbnailExtensions));

	QVariantMap rateLimit;
	rateLimit["enabled"]        = in.rateLimitEnabled;
	rateLimit["max_requests"]   = in.rateLimitMax;
	rateLimit["window_seconds"] = in.rateLimitWindowSeconds;
	rateLimit["applies_to"]     = QString("write");  // POST/DELETE routes only
	json.addMember("rate_limit", QVariant(rateLimit));

	QVariantMap security;
	security["auth_enabled"]         = in.authEnabled;
	security["auth_headers"]         = QStringList() << "X-API-Token" << "Authorization: Bearer";
	security["ip_whitelist_enabled"] = in.ipWhitelistEnabled;
	security["artifact_roots_enabled"] = in.artifactRootsEnabled;
	security["artifact_roots"]         = in.artifactRoots;
	json.addMember("security", QVariant(security));

	// ── Render engines, read live from DzRenderMgr ───────────────────────────
	json.addKey("render_engines");
	json.startObject();
	QStringList selectable;
	QString activeClass;
	json.addKey("registered");
	json.startArray();
	DzRenderMgr* renderMgr = dzApp ? dzApp->getRenderMgr() : nullptr;
	if (renderMgr) {
		DzRenderer* active = renderMgr->getActiveRenderer();
		if (active) activeClass = QString(active->metaObject()->className());
		for (int i = 0; i < renderMgr->getNumRenderers(); ++i) {
			DzRenderer* r = renderMgr->getRenderer(i);
			if (!r) continue;
			QVariantMap m;
			const QString cls = QString(r->metaObject()->className());
			m["class_name"] = cls;
			m["name"]       = r->getName();
			m["active"]     = (r == active);
			json.addItem(QVariant(m));
		}
		for (size_t i = 0; i < sizeof(kSelectableEngines) / sizeof(kSelectableEngines[0]); ++i) {
			const SelectableEngine& e = kSelectableEngines[i];
			if (!e.rendererClass || renderMgr->findRenderer(QString(e.rendererClass)))
				selectable << QString(e.engine);
		}
	}
	json.finishArray();
	json.addMember("selectable", QVariant(selectable));   // values POST /render accepts for "engine"
	if (activeClass.isEmpty()) json.addMemberNull("active_class");
	else                       json.addMember("active_class", activeClass);
	json.addMember("source", engineSource);              // "live" or "snapshot"
	json.addMember("read_at", QDateTime::currentDateTimeUtc().toString(Qt::ISODate));
	json.finishObject();

	// Stable fingerprint of the API surface: schema, routes (incl. companion
	// routes) and feature flags. Changes in limits, settings or render engines
	// don't change it, so clients can cache their route/feature decisions by it.
	hashLines.prepend(QString("schema %1").arg(ServerConfig::CAPABILITIES_SCHEMA_VERSION));
	hashLines.sort();
	QByteArray digest = QCryptographicHash::hash(hashLines.join("\n").toUtf8(),
	                                             QCryptographicHash::Sha1).toHex();
	json.addMember("compatibility_hash", QString::fromLatin1(digest.left(16)));

	json.finishObject();
	return json.toString().toUtf8();
}
