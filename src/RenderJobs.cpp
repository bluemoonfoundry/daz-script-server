// DzScriptServerPane: render, render batch and animation render submission.
// The DazScript they enqueue comes from RenderScriptBuilder.
#include "PaneInternal.h"
#include "RenderScriptBuilder.h"

using namespace RenderScriptBuilder;

// ─── Render submission ───────────────────────────────────────────────────────

HttpResult DzScriptServerPane::handleAsyncRenderEnqueue(const QByteArray& jsonBody,
                                               const QByteArray& correlationId)
{
    const QString corr = QString::fromUtf8(correlationId.constData(), correlationId.size());
    // ── Parse body ────────────────────────────────────────────────────────
    QVariantMap body;
    std::string parseErrDetail;
    if (!JsonStd::parseObject(jsonBody, body, parseErrDetail))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON)));

    // ── Required fields ───────────────────────────────────────────────────
    QString outputPath = body.value("output_path").toString().trimmed();
    {
        ValidationResult vr = RequestValidator::validateRequiredField(outputPath, "output_path");
        if (!vr.valid)
            return HttpResult(vr.httpStatus(), stdToQBA(vr.toErrorJson()));
    }

    // ── Optional fields ───────────────────────────────────────────────────
    int  width       = body.contains("width")        ? body.value("width").toInt()        : 0;
    int  height      = body.contains("height")       ? body.value("height").toInt()       : 0;
    int  iraySamples = 0;
    bool resetMorphs = body.value("reset_morphs").toBool();
    QString camera   = body.value("camera").toString().trimmed();
    QString engine   = body.value("engine").toString().trimmed().toLower();

    {
        std::string err;
        if (!readIraySamples(body, &iraySamples, &err))
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD, err)));
    }
    if (iraySamples > 0 && (engine == "viewport" || engine == "filament"))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "iray_samples requires the iray engine")));

    if ((width > 0) != (height > 0))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "width and height must both be provided or both omitted")));

    if (width < 0 || height < 0)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "width and height must be positive integers")));

    if (!engine.isEmpty()
            && engine != "iray" && engine != "viewport" && engine != "filament")
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "engine must be one of: iray, viewport, filament")));

    // ── Normalise figure list ─────────────────────────────────────────────
    // Accept {figure, morphs} single-figure shorthand or {figures:[{name,morphs},...]}
    QList<FigureSpec> figureSpecs;

    if (body.contains("figures")) {
        QVariantList figs = body.value("figures").toList();
        for (int i = 0; i < figs.size(); ++i) {
            QVariantMap fig = figs[i].toMap();
            QString name = fig.value("name").toString().trimmed();
            if (name.isEmpty())
                return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD,
                    "figures[" + std::to_string(i) + "].name")));
            FigureSpec spec;
            spec.name   = name;
            spec.morphs = fig.value("morphs").toMap();
            figureSpecs.append(spec);
        }
    } else if (body.contains("figure")) {
        QString name = body.value("figure").toString().trimmed();
        if (!name.isEmpty()) {
            FigureSpec spec;
            spec.name   = name;
            spec.morphs = body.value("morphs").toMap();
            figureSpecs.append(spec);
        }
    }

    // ── Pre-flight: validate figure names against the current scene ───────
    // Runs a minimal DazScript on the main thread before enqueuing so that
    // bad figure references surface immediately (not after render queue wait).
    if (!figureSpecs.isEmpty()) {
        QString validateScript = "(function() {\n  var names = [";
        for (int i = 0; i < figureSpecs.size(); ++i) {
            if (i > 0) validateScript += ",";
            validateScript += "\"";
            validateScript += QString::fromStdString(
                JsonStd::escape(JsonStd::qstrToStd(figureSpecs[i].name)));
            validateScript += "\"";
        }
        validateScript +=
            "];\n"
            "  for (var i = 0; i < names.length; i++) {\n"
            "    if (!Scene.findNodeByLabel(names[i])) return 'NOT_FOUND:' + names[i];\n"
            "  }\n"
            "  return 'OK';\n"
            "})()";

        ensurePersistentScript()->clear();
        m_pPersistentScript->setCode(validateScript);
        ScriptRunResult valRunResult = runDazScript(m_pPersistentScript, QVariantMap(), QString());
        if (valRunResult.success) {
            QString valResult = valRunResult.result.toString();
            if (valResult.startsWith("NOT_FOUND:")) {
                QString missing = valResult.mid(10);
                return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                    "Figure not found in scene: " + JsonStd::qstrToStd(missing))));
            }
        }
        // If the validation script itself fails to parse/execute (e.g. Scene API
        // unavailable at startup), proceed — the render script will surface the
        // error at execution time rather than blocking enqueue.
    }

    // ── Generate and enqueue render job ───────────────────────────────────
    QString renderScript = buildRenderScript(
        outputPath, width, height, camera, engine, iraySamples, resetMorphs, figureSpecs);

    AsyncRequestManager::SubmitResult sr = m_pAsyncMgr->submitRender(renderScript, "rnd", corr);
    if (!sr.accepted)
        return HttpResult(503, stdToQBA(ErrorResponse::build(
            ErrorCode::SERVER_UNAVAILABLE, JsonStd::qstrToStd(sr.error))));

    m_pRenderProgress->setOutputPath(sr.id, outputPath);

    appendLog(QString("[%1] [RENDER QUEUED] output:%2 -> %3")
        .arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
        .arg(outputPath).arg(sr.id));

    return buildQueuedResponse(sr.id, sr.submittedAt);
}

HttpResult DzScriptServerPane::handleAsyncRenderBatchEnqueue(const QByteArray& jsonBody,
                                               const QByteArray& correlationId)
{
    const QString corr = QString::fromUtf8(correlationId.constData(), correlationId.size());
    // ── Parse body ────────────────────────────────────────────────────────
    QVariantMap body;
    std::string parseErrDetail;
    if (!JsonStd::parseObject(jsonBody, body, parseErrDetail))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON)));

    // ── Parse base (all fields optional — provides defaults for variants) ─
    QVariantMap base = body.value("base").toMap();

    int     baseWidth       = base.contains("width")        ? base.value("width").toInt()        : 0;
    int     baseHeight      = base.contains("height")       ? base.value("height").toInt()       : 0;
    int     baseIraySamples = 0;
    {
        std::string err;
        if (!readIraySamples(base, &baseIraySamples, &err))
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD, "base." + err)));
    }
    bool    baseResetMorphs = base.value("reset_morphs").toBool();
    QString baseCamera      = base.value("camera").toString().trimmed();
    QString baseEngine      = base.value("engine").toString().trimmed().toLower();

    // Resolve base figures (single-figure shorthand or explicit list)
    QList<FigureSpec> baseFigures;
    if (base.contains("figures")) {
        QVariantList figs = base.value("figures").toList();
        for (int i = 0; i < figs.size(); ++i) {
            QVariantMap fig = figs[i].toMap();
            QString name = fig.value("name").toString().trimmed();
            if (name.isEmpty())
                return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD,
                    "base.figures[" + std::to_string(i) + "].name")));
            FigureSpec spec;
            spec.name   = name;
            spec.morphs = fig.value("morphs").toMap();
            baseFigures.append(spec);
        }
    } else if (base.contains("figure")) {
        QString name = base.value("figure").toString().trimmed();
        if (!name.isEmpty()) {
            FigureSpec spec;
            spec.name   = name;
            spec.morphs = base.value("morphs").toMap();
            baseFigures.append(spec);
        }
    }

    // ── Validate variants array ───────────────────────────────────────────
    if (!body.contains("variants"))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD, "variants")));

    QVariantList variants = body.value("variants").toList();
    if (variants.isEmpty())
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "variants must be a non-empty array")));

    const int MAX_BATCH_VARIANTS = ServerConfig::MAX_BATCH_VARIANTS;
    if (variants.size() > MAX_BATCH_VARIANTS)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "variants exceeds maximum of " + std::to_string(MAX_BATCH_VARIANTS))));

    // ── Validate + pre-flight all variants before enqueuing any ──────────
    struct VariantSpec {
        QString           outputPath;
        int               width, height, iraySamples;
        bool              resetMorphs;
        QString           camera, engine;
        QList<FigureSpec> figures;
        QString           renderScript;
    };
    QList<VariantSpec> specs;
    specs.reserve(variants.size());

    for (int vi = 0; vi < variants.size(); ++vi) {
        QVariantMap v = variants[vi].toMap();
        const std::string viStr = "variants[" + std::to_string(vi) + "]";

        // output_path required per variant
        QString outputPath = v.value("output_path").toString().trimmed();
        {
            ValidationResult vr = RequestValidator::validateRequiredField(outputPath,
                viStr + ".output_path");
            if (!vr.valid)
                return HttpResult(vr.httpStatus(), stdToQBA(vr.toErrorJson()));
        }

        // Merge scalar fields: variant overrides base
        int     width       = v.contains("width")        ? v.value("width").toInt()        : baseWidth;
        int     height      = v.contains("height")       ? v.value("height").toInt()       : baseHeight;
        int     iraySamples = baseIraySamples;
        {
            std::string err;
            if (!readIraySamples(v, &iraySamples, &err))
                return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                    viStr + "." + err)));
        }
        bool    resetMorphs = v.contains("reset_morphs") ? v.value("reset_morphs").toBool(): baseResetMorphs;
        QString camera      = v.contains("camera")       ? v.value("camera").toString().trimmed() : baseCamera;
        QString engine      = v.contains("engine")       ? v.value("engine").toString().trimmed().toLower() : baseEngine;

        if ((width > 0) != (height > 0))
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                viStr + ": width and height must both be provided or both omitted")));
        if (width < 0 || height < 0)
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                viStr + ": width and height must be positive integers")));
        if (!engine.isEmpty()
                && engine != "iray" && engine != "viewport" && engine != "filament")
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                viStr + ".engine must be one of: iray, viewport, filament")));
        if (iraySamples > 0 && (engine == "viewport" || engine == "filament"))
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                viStr + ": iray_samples requires the iray engine")));

        // Merge figures: variant wins if it specifies figures/figure;
        // if variant only has morphs and base has one figure, override its morphs.
        QList<FigureSpec> figures;
        if (v.contains("figures")) {
            QVariantList figs = v.value("figures").toList();
            for (int i = 0; i < figs.size(); ++i) {
                QVariantMap fig = figs[i].toMap();
                QString name = fig.value("name").toString().trimmed();
                if (name.isEmpty())
                    return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD,
                        viStr + ".figures[" + std::to_string(i) + "].name")));
                FigureSpec spec;
                spec.name   = name;
                spec.morphs = fig.value("morphs").toMap();
                figures.append(spec);
            }
        } else if (v.contains("figure")) {
            FigureSpec spec;
            spec.name   = v.value("figure").toString().trimmed();
            spec.morphs = v.value("morphs").toMap();
            figures.append(spec);
        } else if (v.contains("morphs") && baseFigures.size() == 1) {
            // Shorthand: apply morph overrides on top of the single base figure's morphs
            QVariantMap merged = baseFigures[0].morphs;
            QVariantMap overrides = v.value("morphs").toMap();
            for (QVariantMap::const_iterator it = overrides.begin(); it != overrides.end(); ++it)
                merged[it.key()] = it.value();
            FigureSpec spec;
            spec.name   = baseFigures[0].name;
            spec.morphs = merged;
            figures.append(spec);
        } else {
            figures = baseFigures;
        }

        // Pre-flight: validate figure names against the current scene
        if (!figures.isEmpty()) {
            QString validateScript = "(function() {\n  var names = [";
            for (int i = 0; i < figures.size(); ++i) {
                if (i > 0) validateScript += ",";
                validateScript += "\"";
                validateScript += QString::fromStdString(
                    JsonStd::escape(JsonStd::qstrToStd(figures[i].name)));
                validateScript += "\"";
            }
            validateScript +=
                "];\n"
                "  for (var i = 0; i < names.length; i++) {\n"
                "    if (!Scene.findNodeByLabel(names[i])) return 'NOT_FOUND:' + names[i];\n"
                "  }\n"
                "  return 'OK';\n"
                "})()";
            ensurePersistentScript()->clear();
            m_pPersistentScript->setCode(validateScript);
            ScriptRunResult valRunResult = runDazScript(m_pPersistentScript, QVariantMap(), QString());
            if (valRunResult.success) {
                QString valResult = valRunResult.result.toString();
                if (valResult.startsWith("NOT_FOUND:")) {
                    QString missing = valResult.mid(10);
                    return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                        viStr + ": Figure not found in scene: " + JsonStd::qstrToStd(missing))));
                }
            }
        }

        VariantSpec vs;
        vs.outputPath   = outputPath;
        vs.width        = width;
        vs.height       = height;
        vs.iraySamples  = iraySamples;
        vs.resetMorphs  = resetMorphs;
        vs.camera       = camera;
        vs.engine       = engine;
        vs.figures      = figures;
        vs.renderScript = buildRenderScript(
            outputPath, width, height, camera, engine, iraySamples, resetMorphs, figures);
        specs.append(vs);
    }

    // ── Enqueue all variants (all-or-nothing) ─────────────────────────────
    // A full queue rejects the whole batch and enqueues none, so the
    // retryable 503 below is safe to resubmit unchanged (9qph).
    QString batchId = MetricsCollector::generateAsyncId("bat");
    QStringList scripts;
    for (int vi = 0; vi < specs.size(); ++vi)
        scripts.append(specs[vi].renderScript);

    const QVector<AsyncRequestManager::SubmitResult> submitted =
        m_pAsyncMgr->submitRenderBatch(scripts, "rnd", corr);
    if (submitted.size() != specs.size() || !submitted[0].accepted) {
        const QString err = submitted.isEmpty() ? QString("batch rejected") : submitted[0].error;
        return HttpResult(503, stdToQBA(ErrorResponse::build(ErrorCode::SERVER_UNAVAILABLE,
            "No variants queued: " + JsonStd::qstrToStd(err))));
    }

    QStringList requestIds;
    for (int vi = 0; vi < specs.size(); ++vi) {
        m_pRenderProgress->setOutputPath(submitted[vi].id, specs[vi].outputPath);
        requestIds.append(submitted[vi].id);
    }

    // ── Build response ────────────────────────────────────────────────────
    std::string resp = "{\"batch_id\":\"" + JsonStd::qstrToStd(batchId) + "\""
        + ",\"request_ids\":[";
    for (int i = 0; i < requestIds.size(); ++i) {
        if (i > 0) resp += ",";
        resp += "\"" + JsonStd::qstrToStd(requestIds[i]) + "\"";
    }
    resp += "],\"total\":" + std::to_string(requestIds.size()) + "}";

    appendLog(QString("[%1] [BATCH QUEUED] batch:%2 variants:%3")
        .arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
        .arg(batchId)
        .arg(requestIds.size()));

    return HttpResult(200, QByteArray(resp.c_str(), (int)resp.size()));
}

HttpResult DzScriptServerPane::handleAsyncRenderAnimationEnqueue(const QByteArray& jsonBody,
                                               const QByteArray& correlationId)
{
    const QString corr = QString::fromUtf8(correlationId.constData(), correlationId.size());
    // ── Parse body ────────────────────────────────────────────────────────
    QVariantMap body;
    std::string parseErrDetail;
    if (!JsonStd::parseObject(jsonBody, body, parseErrDetail))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON)));

    // ── Required fields ───────────────────────────────────────────────────
    QString outputPath = body.value("output_path").toString().trimmed();
    {
        ValidationResult vr = RequestValidator::validateRequiredField(outputPath, "output_path");
        if (!vr.valid)
            return HttpResult(vr.httpStatus(), stdToQBA(vr.toErrorJson()));
    }
    if (!outputPath.contains("{frame}"))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "output_path must contain the literal token {frame}")));

    if (!body.contains("start_frame"))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD, "start_frame")));
    if (!body.contains("end_frame"))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD, "end_frame")));

    int startFrame = body.value("start_frame").toInt();
    int endFrame   = body.value("end_frame").toInt();
    if (startFrame < 0 || endFrame < 0)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "start_frame and end_frame must be non-negative integers")));
    if (endFrame < startFrame)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "end_frame must be >= start_frame")));

    const int MAX_ANIMATION_FRAMES = ServerConfig::MAX_ANIMATION_FRAMES;
    int frameCount = endFrame - startFrame + 1;
    if (frameCount > MAX_ANIMATION_FRAMES)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "frame range exceeds maximum of " + std::to_string(MAX_ANIMATION_FRAMES) + " frames")));

    // ── Optional fields ───────────────────────────────────────────────────
    int framePadding = body.contains("frame_padding") ? body.value("frame_padding").toInt() : 4;
    if (framePadding < 1 || framePadding > 10)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "frame_padding must be between 1 and 10")));

    int  width  = body.contains("width")  ? body.value("width").toInt()  : 0;
    int  height = body.contains("height") ? body.value("height").toInt() : 0;
    QString camera = body.value("camera").toString().trimmed();
    QString engine = body.value("engine").toString().trimmed().toLower();

    if ((width > 0) != (height > 0))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "width and height must both be provided or both omitted")));
    if (width < 0 || height < 0)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "width and height must be positive integers")));
    if (!engine.isEmpty()
            && engine != "iray" && engine != "viewport" && engine != "filament")
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "engine must be one of: iray, viewport, filament")));

    // ── Pre-flight: validate camera reference against the current scene ───
    if (!camera.isEmpty()) {
        QString validateScript = "(function() {\n"
            "  return Scene.findCameraByLabel(\""
            + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(camera)))
            + "\") ? 'OK' : 'NOT_FOUND';\n"
            "})()";
        ensurePersistentScript()->clear();
        m_pPersistentScript->setCode(validateScript);
        ScriptRunResult valRunResult = runDazScript(m_pPersistentScript, QVariantMap(), QString());
        if (valRunResult.success && valRunResult.result.toString() == "NOT_FOUND")
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                "Camera not found in scene: " + JsonStd::qstrToStd(camera))));
    }

    // ── Generate and enqueue animation render job ─────────────────────────
    // Server-owned per-job frame report (see buildAnimationRenderScript).
    // A random name, not the request ID: the script is built before the job
    // is submitted, and the name must not be guessable or reused.
    // No weak fallback (W15): an 8-char QUuid is 32 bits and not CSPRNG-backed
    // on Qt 4, so refuse the job instead.
    const QString reportToken = SecureRandom::generateHexToken(8);
    if (reportToken.isEmpty())
        return HttpResult(503, stdToQBA(ErrorResponse::build(ErrorCode::SERVER_UNAVAILABLE,
            "secure random source unavailable; cannot create the render's frame report")));
    const QString frameReportFile =
        QDir(QDir::tempPath()).filePath("dss-frames-" + reportToken + ".jsonl");

    QString renderScript = buildAnimationRenderScript(
        outputPath, startFrame, endFrame, framePadding, width, height, camera, engine,
        frameReportFile);

    AsyncRequestManager::SubmitResult sr =
        m_pAsyncMgr->submitRender(renderScript, "rnd", corr, frameReportFile);
    if (!sr.accepted)
        return HttpResult(503, stdToQBA(ErrorResponse::build(
            ErrorCode::SERVER_UNAVAILABLE, JsonStd::qstrToStd(sr.error))));

    m_pRenderProgress->setOutputPath(sr.id, outputPath);

    appendLog(QString("[%1] [ANIMATION RENDER QUEUED] frames:%2-%3 output:%4 -> %5")
        .arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
        .arg(startFrame).arg(endFrame)
        .arg(outputPath).arg(sr.id));

    return buildQueuedResponse(sr.id, sr.submittedAt);
}
