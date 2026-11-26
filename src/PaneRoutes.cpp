// DzScriptServerPane::setupRoutes(): the middleware chains and the route
// table (kept in parity with openapi.yaml by scripts/check_openapi_parity.py),
// plus the artifact thumbnail route.
#include "PaneInternal.h"

// ─── Route setup ──────────────────────────────────────────────────────────────
//
// THREADING RULE: httplib invokes these handlers on raw std::threads (not QThreads).
// Sync handlers cross to the main thread only through callOnMainThread()
// (MainThreadCall), so a request still queued behind a busy main thread gives
// up instead of pinning its slot. On
// Studio 6, async script enqueue handlers may build local reentrant Qt Core
// values and call mutex-protected services; Studio 4 crosses to the main thread
// because its JSON parser uses QScriptEngine. Execution later reaches the main
// thread through a queued wake-up. No worker may touch GUI, DzScript, DAZ SDK,
// or shared mutable pane state.

void DzScriptServerPane::setupRoutes()
{
	// ── Middleware chains ─────────────────────────────────────────────────────
	//
	// Every authenticated route runs one of these two chains, so the IP whitelist
	// always runs before auth. tests/test_route_security.py enforces this.
	//
	// Write chain: every POST/DELETE route (anything that executes, mutates or
	// writes to disk). BodySizeMiddleware is defence in depth: httplib's
	// set_payload_max_length (startServer) already stops oversized bodies while
	// they are being read.
	m_pWriteChain.reset(new MiddlewareChain());
	m_pWriteChain->add(new IPWhitelistMiddleware(m_ipWhitelist, this));
	m_pWriteChain->add(new RateLimitMiddleware(m_rateLimiter, this));
	m_pWriteChain->add(new BodySizeMiddleware(m_nMaxBodySizeMB));
	m_pWriteChain->add(new AuthMiddleware(m_auth, m_metrics, this));

	// Read chain: GET polling and SSE routes. Not rate limited, because clients
	// poll /requests/:id/status in a loop and a 60 req/60s window would throttle
	// a single well-behaved job watcher.
	m_pReadChain.reset(new MiddlewareChain());
	m_pReadChain->add(new IPWhitelistMiddleware(m_ipWhitelist, this));
	m_pReadChain->add(new AuthMiddleware(m_auth, m_metrics, this));

	// ── Request handlers ──────────────────────────────────────────────────────
	m_pStatusHandler.reset(new StatusHandler(DZSRV_VERSION_STR, this));
	m_pHealthHandler.reset(new HealthHandler(this));
	m_pMetricsHandler.reset(new MetricsHandler(this));
	m_pCapabilitiesHandler.reset(new CapabilitiesHandler(this));
	m_pExecuteHandler.reset(new ExecuteScriptHandler(this, m_nQueueTimeoutSec));
	m_pRegisterHandler.reset(new ScriptRegisterHandler(this));
	m_pScriptListHandler.reset(new ScriptListHandler(this));
	m_pScriptDeleteHandler.reset(new ScriptDeleteHandler(this));
	m_pScriptExecHandler.reset(new ScriptExecuteHandler(this, m_nQueueTimeoutSec));
	// Snapshot the GUI-owned limit before httplib starts its worker threads.
	// The corresponding control is disabled while the server is running.
	m_pAsyncExecHandler.reset(new AsyncExecuteHandler(this, m_nMaxScriptLengthKB));
	m_pAsyncScriptHandler.reset(new AsyncScriptHandler(this));
	m_pAsyncStatusHandler.reset(new AsyncStatusHandler(this));
	m_pAsyncResultHandler.reset(new AsyncResultHandler(this));
	m_pAsyncCancelHandler.reset(new AsyncCancelHandler(this));
	m_pAsyncListHandler.reset(new AsyncListHandler(this));
	m_pRenderHandler.reset(new RenderHandler(this));
	m_pRenderBatchHandler.reset(new RenderBatchHandler(this));
	m_pRenderAnimationHandler.reset(new RenderAnimationHandler(this));
	m_pRenderCancelHandler.reset(new RenderCancelHandler(this));
	m_pSaveCopyHandler.reset(new SaveCopyHandler(this));
	m_pGeometryFramesHandler.reset(new GeometryFramesHandler(this));

	// ── Routes ───────────────────────────────────────────────────────────────

	m_pServer->Get("/status", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		m_pStatusHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/health", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		m_pHealthHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/metrics", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		m_pMetricsHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/capabilities", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pReadChain->run(ctx)) m_pCapabilitiesHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Post("/execute", [this](const httplib::Request& req, httplib::Response& res) {
		runSyncJobRoute(req, res, m_pExecuteHandler.get());
	});

	m_pServer->Post("/scripts/register", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pRegisterHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/scripts", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pReadChain->run(ctx)) m_pScriptListHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Delete("/scripts/([^/]+)", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pScriptDeleteHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Post("/scripts/([^/]+)/execute", [this](const httplib::Request& req, httplib::Response& res) {
		runSyncJobRoute(req, res, m_pScriptExecHandler.get());
	});

	// ── Async endpoints ──────────────────────────────────────────────────────

	m_pServer->Post("/execute/async", [this](const httplib::Request& req, httplib::Response& res) {
		runJobRoute(req, res, m_pAsyncExecHandler.get(), true);
	});

	m_pServer->Post("/scripts/([^/]+)/async", [this](const httplib::Request& req, httplib::Response& res) {
		runJobRoute(req, res, m_pAsyncScriptHandler.get(), true);
	});

	m_pServer->Get("/requests/([^/]+)/status", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pReadChain->run(ctx)) m_pAsyncStatusHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/requests/([^/]+)/result", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pReadChain->run(ctx)) m_pAsyncResultHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Delete("/requests/([^/]+)", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pAsyncCancelHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/requests", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pReadChain->run(ctx)) m_pAsyncListHandler->handle(ctx);
		applyContext(ctx, res);
	});

	// GET /artifacts/:job_id and GET /artifacts/:job_id/:artifact_id
	//
	// Read chain (IP whitelist -> auth), like the other polling GETs: a client
	// fetching a large file in Range chunks must not trip the rate limiter.
	// Downloads only serve files in the job's output manifest whose real
	// path is inside the allowed artifact folders (ArtifactRoots); see
	// ArtifactRoutes. ?thumbnail=<px> goes to
	// serveArtifactThumbnail(), which decodes on the main thread.
	m_pServer->Get("/artifacts/([^/]+)", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (!m_pReadChain->run(ctx)) { applyContext(ctx, res); return; }
		ArtifactRoutes::list(*m_pAsyncMgr, m_artifactRoots, m_thumbnailExtensions, req, res);
	});

	m_pServer->Get("/artifacts/([^/]+)/([^/]+)", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (!m_pReadChain->run(ctx)) { applyContext(ctx, res); return; }
		if (req.has_param("thumbnail"))
			serveArtifactThumbnail(req, res);
		else
			ArtifactRoutes::serve(*m_pAsyncMgr, m_artifactRoots, req, res);
	});

	// ── Render endpoints ──────────────────────────────────────────────────────

	m_pServer->Post("/render", [this](const httplib::Request& req, httplib::Response& res) {
		runJobRoute(req, res, m_pRenderHandler.get(), true);
	});

	m_pServer->Post("/render/batch", [this](const httplib::Request& req, httplib::Response& res) {
		runJobRoute(req, res, m_pRenderBatchHandler.get(), true);
	});

	m_pServer->Post("/render/animation", [this](const httplib::Request& req, httplib::Response& res) {
		runJobRoute(req, res, m_pRenderAnimationHandler.get(), true);
	});

	m_pServer->Post("/render/([^/]+)/cancel", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pRenderCancelHandler->handle(ctx);
		applyContext(ctx, res);
	});

	// ── Scene I/O endpoints ───────────────────────────────────────────────────

	m_pServer->Post("/scene/save-copy", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pSaveCopyHandler->handle(ctx);
		applyContext(ctx, res);
	});

	// Fork: deformed figure vertices for a frame list as binary (GeometryExport.h)
	m_pServer->Post("/geometry/frames", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pGeometryFramesHandler->handle(ctx);
		applyContext(ctx, res);
	});

	// ── Scene event stream (SSE) ──────────────────────────────────────────────
	//
	// GET /scene/events[?filter=node,selection,scene,time,render,light,camera,skeleton]
	//
	// Streams DAZ scene-change notifications as Server-Sent Events.  The
	// connection is kept open indefinitely; a ":keepalive" comment is sent
	// every SSE_KEEPALIVE_INTERVAL_MS (ServerConfig) so clients can detect
	// disconnects.
	//
	// Each event frame:   data: {"type":"...","ts":<ms>,"data":{...}}\n\n
	// Keepalive frame:    :keepalive\n\n

	m_pServer->Get("/scene/events", [this](const httplib::Request& req, httplib::Response& res) {
		// Auth check — run the chain synchronously before entering streaming mode.
		// We cannot call applyContext() here (it would finalize the response body),
		// so on failure we set status/content directly.
		{
			auto ctx = toContext(req);
			if (!m_pReadChain->run(ctx)) {
				res.status = ctx.responseStatus;
				res.set_content(ctx.responseBody, "application/json");
				return;
			}
		}

		// ?filter=node,selection,... → bitmask. Absent or empty → all categories.
		const int filterMask = req.has_param("filter")
			? SceneEventFilter::parse(req.get_param_value("filter"))
			: static_cast<int>(SceneEventFilter::All);

		res.set_header("Cache-Control", "no-cache");
		res.set_header("Connection",    "keep-alive");
		res.set_header("X-Accel-Buffering", "no"); // disable nginx proxy buffering

		SubscriberQueue* queue = new SubscriberQueue(filterMask);
		m_pEventBroker->registerSubscriber(queue);
		QMetaObject::invokeMethod(this, "updateEventClientsLabel", Qt::QueuedConnection);

		// The chunked content provider is called repeatedly by httplib on the
		// HTTP handler thread until it returns false or the client disconnects.
		// The pop timeout is SSE_KEEPALIVE_INTERVAL_MS, so each idle iteration
		// writes a keepalive (see ServerConfig for the write-timeout bound).
		res.set_chunked_content_provider("text/event-stream",
			[queue](size_t /*offset*/, httplib::DataSink& sink) -> bool {
				QString event = queue->pop(ServerConfig::SSE_KEEPALIVE_INTERVAL_MS);

				if (event.isEmpty()) {
					// Timeout or closed queue — send keepalive to prove the
					// connection is live.  A closed queue returns "" every call,
					// so on server shutdown this unblocks quickly and the next
					// is_shutting_down() check ends the loop.
					static const char ka[] = ":keepalive\n\n";
					return sink.write(ka, sizeof(ka) - 1);
				}

				QByteArray payload = ("data: " + event + "\n\n").toUtf8();
				return sink.write(payload.constData(), static_cast<size_t>(payload.size()));
			},
			[this, queue](bool /*success*/) {
				// Resource releaser — called exactly once when the stream closes.
				// stopServer() guarantees the broker outlives all releasers by
				// deleting it only after m_pServerThread->wait() returns (which
				// joins all request-handler threads via ThreadPool::shutdown()).
				m_pEventBroker->unregisterSubscriber(queue);
				delete queue;
				QMetaObject::invokeMethod(this, "updateEventClientsLabel", Qt::QueuedConnection);
			}
		);
	});

	// GET /render/:id/progress
	//
	// SSE stream: emits a single "progress" event (percent:0) when the render
	// starts executing, then a terminal "complete" or "error" event when done.
	// DAZ SDK exposes no per-frame progress signal, so no intermediate percent
	// updates are possible. Clients connecting after completion receive the
	// stored terminal event immediately.
	m_pServer->Get("/render/([^/]+)/progress", [this](const httplib::Request& req, httplib::Response& res) {
		{
			auto ctx = toContext(req);
			if (!m_pReadChain->run(ctx)) {
				res.status = ctx.responseStatus;
				res.set_content(ctx.responseBody, "application/json");
				return;
			}
		}

		QString requestId = QString::fromStdString(req.matches[1].str());
		if (!requestId.startsWith("rnd-")) {
			// 404 (not 400 NOT_A_RENDER_REQUEST): no render exists at this path.
			respondError(res, ErrorCode::REQUEST_NOT_FOUND, requestId.toStdString());
			return;
		}

		auto statusPair = m_pAsyncMgr->getStatusJson(requestId.toStdString());
		if (statusPair.first == 404) {
			respondError(res, ErrorCode::REQUEST_NOT_FOUND, requestId.toStdString());
			return;
		}

		SubscriberQueue* queue = new SubscriberQueue();
		if (!m_pRenderProgress->watchRequest(requestId, queue)) {
			delete queue;
			respondError(res, ErrorCode::REQUEST_NOT_FOUND, requestId.toStdString());
			return;
		}

		res.set_header("Cache-Control",    "no-cache");
		res.set_header("Connection",       "keep-alive");
		res.set_header("X-Accel-Buffering","no");
		QMetaObject::invokeMethod(this, "updateEventClientsLabel", Qt::QueuedConnection);

		RenderProgressBroker* broker = m_pRenderProgress;
		AsyncRequestManager*  asyncMgr = m_pAsyncMgr;
#if DAZ_SDK_MAJOR_VERSION >= 6
		// Studio 6 shims print(), so the [DAZPY_FRAME] marker never reaches
		// onMessagePosted. Poll the job's frame report (ingested here on the
		// HTTP thread, like status polling) and feed the broker, which drops
		// frames already sent. Shorter pop so frames show up promptly;
		// keepalives still go out every SSE_KEEPALIVE_INTERVAL_MS.
		const int  popMs          = ServerConfig::SSE_FRAME_POLL_MS;
		const bool pollFrames     = true;
#else
		const int  popMs          = ServerConfig::SSE_KEEPALIVE_INTERVAL_MS;
		const bool pollFrames     = false;
#endif
		std::shared_ptr<int> idleMs = std::make_shared<int>(0);
		res.set_chunked_content_provider("text/event-stream",
			[queue, broker, asyncMgr, requestId, popMs, pollFrames, idleMs](
				size_t, httplib::DataSink& sink) -> bool {
				if (pollFrames && !queue->isClosed()) {
					int frame = 0, total = 0;
					if (asyncMgr->frameProgress(requestId, &frame, &total))
						broker->notifyProgress(requestId, frame, total);
				}
				QString event = queue->pop(popMs);
				// End only once the queue is closed AND drained, so a progress
				// event queued just before the terminal one can't cut the
				// stream short. close() follows the final push, so re-pop once
				// after seeing it closed. End with sink.done() (the zero-length
				// chunk), not return false, which aborts the connection and
				// makes clients that read to EOF fail (7qv4).
				if (event.isEmpty() && queue->isClosed())
					event = queue->pop(0);
				if (event.isEmpty() && queue->isClosed()) {
					sink.done();
					return true;
				}
				if (event.isEmpty()) {
					*idleMs += popMs;
					if (*idleMs < ServerConfig::SSE_KEEPALIVE_INTERVAL_MS) return true;
					*idleMs = 0;
					static const char ka[] = ":keepalive\n\n";
					return sink.write(ka, sizeof(ka) - 1);
				}
				*idleMs = 0;
				QByteArray payload = event.toUtf8();
				return sink.write(payload.constData(), payload.size());
			},
			[this, broker, requestId, queue](bool) {
				broker->unwatchRequest(requestId, queue);
				delete queue;
				QMetaObject::invokeMethod(this, "updateEventClientsLabel", Qt::QueuedConnection);
			}
		);
	});

	applyPluginRoutes();
}

// ─── Artifact thumbnails ─────────────────────────────────────────────────────

// GET /artifacts/:job_id/:artifact_id?thumbnail=<px>[&format=png|jpeg]
//
// HTTP worker: validation, the file read (C stdio) and the cache never touch
// QtGui. Decoding is posted to the main thread (handleThumbnailJob) and waited
// on with a timeout, so a long job holding the main thread yields 503
// STUDIO_BUSY instead of a hung request. See ArtifactThumbnail.h.
void DzScriptServerPane::serveArtifactThumbnail(const httplib::Request& req, httplib::Response& res)
{
	using namespace ArtifactThumbnail;

	if (!ArtifactRoutes::idsValid(req, res)) return;
	int         px = 0;
	Format      format = FORMAT_PNG;
	std::string paramError;
	if (!parseParams(req.get_param_value("thumbnail"), req.get_param_value("format"),
	                 req.has_param("format"), &px, &format, &paramError)) {
		respondError(res, ErrorCode::INVALID_FIELD, paramError);
		return;
	}

	QString path;
	FILE*   file  = 0;
	qint64  size  = 0;
	qint64  mtime = 0;
	if (!ArtifactRoutes::openDeclared(*m_pAsyncMgr, m_artifactRoots, req, res, &path, &file, &size, &mtime)) return;

	if (!extensionIn(path, m_thumbnailExtensions)) {
		std::fclose(file);
		const QByteArray decodable = m_thumbnailExtensions.join(", ").toUtf8();
		respondError(res, ErrorCode::THUMBNAIL_UNSUPPORTED,
			"no image decoder for this file type (decodable: "
			+ qbaToStd(decodable) + ")");
		return;
	}
	if (size > kMaxSourceBytes) {
		std::fclose(file);
		respondError(res, ErrorCode::THUMBNAIL_UNSUPPORTED,
			"file is larger than the " + std::to_string(kMaxSourceBytes / (1024 * 1024))
			+ " MB thumbnail limit");
		return;
	}

	// Image headers go on success only, never on an error envelope.
	auto sendImage = [&](const QByteArray& img, const char* cacheState) {
		res.set_header("Cache-Control", "private, no-store");
		res.set_header("X-Content-Type-Options", "nosniff");
		res.set_header("Content-Disposition",
			ArtifactFile::contentDisposition(path + ".thumb." + extension(format)).constData());
		res.set_header("X-Thumbnail-Cache", cacheState);
		res.status = 200;
		res.set_content(img.constData(), static_cast<size_t>(img.size()), contentType(format));
	};

	const QString cacheKey = Cache::key(path, size, mtime, px, format);
	QByteArray image;
	if (m_thumbnailCache.get(cacheKey, &image)) {
		std::fclose(file);
		sendImage(image, "hit");
		return;
	}

	if (isMainThreadBusy()) {
		std::fclose(file);
		res.set_header("Retry-After", ServerConfig::RETRY_AFTER_BUSY_SEC);
		respondError(res, ErrorCode::STUDIO_BUSY, mainThreadBusyMessage());
		return;
	}

	QByteArray source;
	source.resize(static_cast<int>(size));
	size_t got = 0;
	while (got < static_cast<size_t>(size)) {
		const size_t n = std::fread(source.data() + got, 1, static_cast<size_t>(size) - got, file);
		if (n == 0) break;
		got += n;
	}
	std::fclose(file);
	if (got != static_cast<size_t>(size)) {
		respondError(res, ErrorCode::ARTIFACT_UNAVAILABLE, "declared file changed while it was being read");
		return;
	}

	Job* job = new Job();
	job->source = source;
	job->maxPx  = px;
	job->format = format;
	if (!QMetaObject::invokeMethod(this, "handleThumbnailJob", Qt::QueuedConnection,
	                               Q_ARG(qulonglong, static_cast<qulonglong>(reinterpret_cast<quintptr>(job))))) {
		release(job);   // the main thread's reference
		release(job);   // ours
		respondError(res, ErrorCode::INTERNAL_ERROR, "could not reach the main thread");
		return;
	}
	if (!job->done.tryAcquire(1, kMainThreadTimeoutMs)) {
		// The main thread skips the job when it gets to it and frees it.
		job->abandoned.fetchAndStoreOrdered(1);
		release(job);
		res.set_header("Retry-After", ServerConfig::RETRY_AFTER_BUSY_SEC);
		respondError(res, ErrorCode::STUDIO_BUSY,
			"DAZ Studio's main thread did not get to the thumbnail within "
			+ std::to_string(kMainThreadTimeoutMs / 1000) + " s");
		return;
	}

	const bool ok = job->ok;
	image = job->image;
	const QByteArray error = job->error.toUtf8();
	release(job);
	if (!ok) {
		respondError(res, ErrorCode::THUMBNAIL_UNSUPPORTED, qbaToStd(error));
		return;
	}
	m_thumbnailCache.put(cacheKey, image);
	sendImage(image, "miss");
}

void DzScriptServerPane::handleThumbnailJob(qulonglong job)
{
	ArtifactThumbnail::run(reinterpret_cast<ArtifactThumbnail::Job*>(static_cast<quintptr>(job)));
}
