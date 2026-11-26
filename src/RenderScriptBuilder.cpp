// DazScript generated for render jobs (see RenderScriptBuilder.h). Pure string
// building with no pane state and no DAZ SDK calls.
#include "RenderScriptBuilder.h"
#include "JsonStd.h"

namespace RenderScriptBuilder {

namespace {

// DS6 DazScript: mgr["renderFinished(bool)"] is undefined, so a chained
// .connect() throws "Cannot call method 'connect' of undefined" before
// doRender() runs. Look up the signal, then connect only if present.
static QString bindRenderFinishedJs(const char* mgrVar)
{
    return QString(
        "  var _finishedSig = null;\n"
        "  try { _finishedSig = %1[\"renderFinished(bool)\"]; } catch (_eSig) { _finishedSig = null; }\n"
        "  if (!(_finishedSig && typeof _finishedSig.connect === \"function\")) {\n"
        "    try { _finishedSig = %1.renderFinished; } catch (_eSig2) { _finishedSig = null; }\n"
        "  }\n"
        "  var _finishedBound = _finishedSig && typeof _finishedSig.connect === \"function\";\n"
        "  if (_finishedBound) _finishedSig.connect(_onRenderFinished);\n"
    ).arg(QLatin1String(mgrVar));
}

static const char* unbindRenderFinishedJs =
    "    if (_finishedBound && _finishedSig && typeof _finishedSig.disconnect === \"function\")\n"
    "      _finishedSig.disconnect(_onRenderFinished);\n";

// Throws unless a render left a non-empty file at path. renderFinished(true)
// also fires for a render that wrote nothing (alaz: viewport engine, path on
// an unmapped drive), which used to report "completed" with 0 bytes.
static const char* requireRenderOutputJs =
    "  function _requireRenderOutput(path) {\n"
    "    var fi = new DzFileInfo(path);\n"
    "    if (!fi.exists() || !(fi.size() > 0))\n"
    "      throw new Error(\"Render finished but wrote no file to \" + path"
    " + \" (is the folder writable?)\");\n"
    "  }\n";

} // namespace

// Reads an optional "iray_samples" field from a request object. Absent → keeps
// *out (the caller's default); 0 means "use the scene's Iray setting". Rejects
// non-integers and negatives so a typo can't silently become "scene default".
// The upper bound is the live property's clamp, checked in the render script.
bool readIraySamples(const QVariantMap& m, int* out, std::string* err)
{
    if (!m.contains("iray_samples")) return true;
    const QVariant v = m.value("iray_samples");
    bool numeric = false;
    switch (v.type()) {
    case QVariant::Int: case QVariant::LongLong:
    case QVariant::UInt: case QVariant::ULongLong: case QVariant::Double:
        numeric = true; break;
    default: break;
    }
    const double d = numeric ? v.toDouble() : -1.0;
    if (!numeric || d != (double)(long long)d || d < 0 || d > 2147483647.0) {
        *err = "iray_samples must be a non-negative integer (0 = scene default)";
        return false;
    }
    *out = (int)d;
    return true;
}

// Builds the DazScript that applies morphs and triggers the render.
// The script runs on the main thread via processNextAsyncRequest().
//
// Structure:
//   1. Re-validate figure refs (belt-and-suspenders; scene may have changed since enqueue).
//   2. Optionally reset all float properties on each figure to default (reset_morphs).
//   3. Apply morphs dict via findPropertyByLabel(); unknown keys are silently skipped.
//   4. Configure render options and call App.getRenderMgr().render(opts).
//   5. Return {success:true, output_path:"..."} as a JS object.
//
// NOTE: DAZ DazScript render options method names (setImageFile, setAspectWidth,
// setAspectHeight, setActiveCamera) need to be verified against a running DAZ Studio
// instance. The names used here are based on the DAZ SDK docs and existing examples.
QString buildRenderScript(
    const QString& outputPath,
    int width, int height,
    const QString& camera,
    const QString& engine,
    int iraySamples,
    bool resetMorphs,
    const QList<FigureSpec>& figures)
{
    // Embed figure specs as a JSON array literal — valid JS object literal syntax.
    QString figureJson = "[";
    for (int i = 0; i < figures.size(); ++i) {
        if (i > 0) figureJson += ",";
        figureJson += "{\"name\":\"";
        figureJson += QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(figures[i].name)));
        figureJson += "\",\"morphs\":";
        figureJson += QString::fromStdString(JsonStd::variantToJson(QVariant(figures[i].morphs)));
        figureJson += "}";
    }
    figureJson += "]";

    QString outputPathEsc = QString::fromStdString(
        JsonStd::escape(JsonStd::qstrToStd(outputPath)));
    QString cameraEsc = camera.isEmpty() ? QString("null")
        : "\"" + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(camera))) + "\"";
    QString engineEsc = engine.isEmpty() ? QString("null")
        : "\"" + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(engine))) + "\"";

    QString script;
    script += "(function() {\n";

    // ── Figure specs ──────────────────────────────────────────────────────
    script += "  var figures = " + figureJson + ";\n";
    script += "  var outputPath = \"" + outputPathEsc + "\";\n";
    script += "  var cameraName = " + cameraEsc + ";\n";
    script += "  var engineName = " + engineEsc + ";\n";
    script += "  var width = " + QString::number(width) + ";\n";
    script += "  var height = " + QString::number(height) + ";\n";
    script += "  var iraySamples = " + QString::number(iraySamples) + ";\n";
    script += "  var resetMorphs = " + QString(resetMorphs ? "true" : "false") + ";\n\n";

    // ── Pre-flight: validate all figure references ────────────────────────
    script +=
        "  for (var i = 0; i < figures.length; i++) {\n"
        "    if (!Scene.findNodeByLabel(figures[i].name))\n"
        "      return {success: false, error: 'Figure not found: ' + figures[i].name};\n"
        "  }\n\n";

    // ── Reset morphs ──────────────────────────────────────────────────────
    // Resets all DzFloatProperty values to their defaults on each figure.
    // This gives a clean morph baseline before applying the variant's morph dict.
    script +=
        "  if (resetMorphs) {\n"
        "    for (var i = 0; i < figures.length; i++) {\n"
        "      var node = Scene.findNodeByLabel(figures[i].name);\n"
        "      var props = node.getPropertyList();\n"
        "      for (var j = 0; j < props.length; j++) {\n"
        "        if (props[j].inherits('DzFloatProperty'))\n"
        "          props[j].setValue(props[j].getDefaultValue());\n"
        "      }\n"
        "    }\n"
        "  }\n\n";

    // ── Apply morphs ──────────────────────────────────────────────────────
    // Unknown morph names are silently skipped (non-fatal per design decision).
    script +=
        "  for (var i = 0; i < figures.length; i++) {\n"
        "    var node = Scene.findNodeByLabel(figures[i].name);\n"
        "    var morphDict = figures[i].morphs;\n"
        "    for (var k in morphDict) {\n"
        "      if (morphDict.hasOwnProperty(k)) {\n"
        "        var prop = node.findPropertyByLabel(k);\n"
        "        if (prop) prop.setValue(morphDict[k]);\n"
        "      }\n"
        "    }\n"
        "  }\n\n";

    // ── Configure render options ──────────────────────────────────────────
    // SDK-verified method names (dzrenderoptions.h / dzrendermgr.h / dzscene.h):
    //   renderImgFilename   Q_PROPERTY WRITE setRenderImgFilename
    //   renderImgToId       Q_PROPERTY WRITE setRenderImgToId  (2 = DirectToFile)
    //   imageSize           Q_PROPERTY WRITE setImageSize (QSize)
    //   Scene.findCameraByLabel()  confirmed in dzscene.h
    //   MainWindow.getViewportMgr().getActiveViewport().get3DViewport().setCamera()
    //     is the verified viewport-camera setter (see dazpy/_viewport.py,
    //     vangard_daz_mcp/_registry.py's _SET_ACTIVE_CAMERA_SCRIPT). Neither
    //     App.getViewportMgr() nor DzViewportMgr.setActiveCamera() exist on this
    //     DAZ Studio version — both throw TypeError; don't reintroduce them.
    //   opts.camera  is the property doRender() actually reads to pick the render
    //     camera — setting only the viewport's active camera leaves this stale/null
    //     and produces a black render. Must set both (see dazpy/_render.py, and
    //     vangard_daz_mcp/_registry.py's camera-preset/render scripts).
    //   renderMgr.doRender(opts)  confirmed in dzrendermgr.h
    //   Engine switching: "viewport" sets opts.renderType = ScreenShot; "iray"/
    //     "filament" look the renderer up by class name via
    //     renderMgr.findRenderer() (runtime-registered, so not in the SDK
    //     headers), activate it with setActiveRenderer(), set renderType =
    //     Software, then read both back and throw on any mismatch (below).
    //   iray_samples: not a DzRenderOptions property — applied below through
    //     the Iray renderer's property holder ("Max Samples").
    script +=
        "  var renderMgr = App.getRenderMgr();\n"
        "  var opts = renderMgr.getRenderOptions();\n"
        "  opts.renderImgFilename = outputPath;\n"
        "  opts.renderImgToId = 2;\n";  // DirectToFile

    // QSize constructor confirmed in DAZ DazScript: new QSize(w, h)
    // Qt.size() is NOT available — Qt global is undefined in this engine.
    script +=
        "  if (width > 0) opts.imageSize = new QSize(width, height);\n";

    script +=
        "  if (cameraName) {\n"
        "    var cam = Scene.findCameraByLabel(cameraName);\n"
        "    if (cam) {\n"
        "      opts.camera = cam;\n"
        "      var viewportMgr = MainWindow.getViewportMgr();\n"
        "      var activeViewport = viewportMgr ? viewportMgr.getActiveViewport() : null;\n"
        "      if (activeViewport) activeViewport.get3DViewport().setCamera(cam);\n"
        "    }\n"
        "  }\n";

    // renderType is the effective operation selector. Active renderer identity
    // is read separately because DAZ retains it during Viewport/OpenGL renders.
    script +=
        "  var engineReadback = null;\n"
        "  if (engineName) {\n"
        "    var requestedEngine = engineName.toLowerCase();\n"
        "    var engineMap = {\"iray\": \"DzIrayRenderer\", \"filament\": \"DzFilamentRenderer\"};\n"
        "    var requestedClass = engineMap[requestedEngine];\n"
        "    if (requestedEngine === \"viewport\") {\n"
        "      opts.renderType = opts.ScreenShot;\n"
        "    } else {\n"
        "      if (!requestedClass) throw new Error(\"Unknown render engine request: \" + requestedEngine);\n"
        "      var requestedRenderer = renderMgr.findRenderer(requestedClass);\n"
        "      if (!requestedRenderer) throw new Error(\"Render engine is not registered: \" + requestedClass);\n"
        "      renderMgr.setActiveRenderer(requestedRenderer);\n"
        "      opts.renderType = opts.Software;\n"
        "    }\n"
        "    opts.applyChanges();\n"
        "    var effectiveType = Number(opts.renderType);\n"
        "    var effectiveRenderer = renderMgr.getActiveRenderer();\n"
        "    var effectiveClass = effectiveRenderer ? String(effectiveRenderer.className()) : null;\n"
        "    var effectiveName = effectiveRenderer ? String(effectiveRenderer.getName()) : null;\n"
        "    var exactMatch = requestedEngine === \"viewport\"\n"
        "      ? effectiveType === Number(opts.ScreenShot)\n"
        "      : effectiveType === Number(opts.Software) && effectiveClass === requestedClass;\n"
        "    if (!exactMatch) throw new Error(\"Render engine readback mismatch for request: \" + requestedEngine);\n"
        "    var typeName = effectiveType === Number(opts.ScreenShot) ? \"ScreenShot\"\n"
        "      : effectiveType === Number(opts.HardwareAssisted) ? \"HardwareAssisted\"\n"
        "      : effectiveType === Number(opts.Software) ? \"Software\" : null;\n"
        "    engineReadback = {\n"
        "      selector_schema: 1,\n"
        "      status: requestedEngine === \"iray\" ? \"verified_iray\" : \"verified_non_iray\",\n"
        "      engine: requestedEngine === \"iray\" ? \"iray\" : (requestedEngine === \"viewport\" ? \"viewport_gl\" : \"other_non_iray\"),\n"
        "      method: \"render_settings_engine_selector\",\n"
        "      reason: requestedEngine === \"iray\" ? null : \"non_iray_engine\",\n"
        "      render_type: {raw: effectiveType, name: typeName, provenance: {kind: \"live_readback\", source: \"DzRenderOptions.renderType\"}},\n"
        "      active_renderer: {class_name: effectiveClass, name: effectiveName, provenance: {kind: \"live_readback\", source: \"DzRenderMgr.getActiveRenderer\"}}\n"
        "    };\n"
        "  }\n";

    // iray_samples: Iray's sample cap is the "Max Samples" DzIntProperty on
    // renderMgr.getActiveRenderer().getPropertyHolder() (confirmed live on
    // DS 6.26: clamped -1..25000; same path dazpy/_render.py uses for
    // max_samples). It's a per-render override: the previous value is
    // restored after doRender() so the request doesn't leak into the user's
    // persistent render settings. The request fails (rather than silently
    // rendering with the scene default) if the effective render isn't an
    // Iray software render, the property can't be found, the value is out
    // of the property's range, or the readback doesn't match.
    script +=
        "  var irayReadback = null;\n"
        "  var _maxSamplesProp = null;\n"
        "  var _prevMaxSamples = null;\n"
        "  if (iraySamples > 0) {\n"
        "    var _iRenderer = renderMgr.getActiveRenderer();\n"
        "    var _iClass = _iRenderer ? String(_iRenderer.className()) : null;\n"
        "    if (_iClass !== \"DzIrayRenderer\" || Number(opts.renderType) !== Number(opts.Software))\n"
        "      throw new Error(\"iray_samples requires an Iray render; effective renderer is \" + _iClass"
        " + \" with renderType \" + Number(opts.renderType));\n"
        "    var _iHolder = _iRenderer.getPropertyHolder();\n"
        "    var _iProp = _iHolder ? _iHolder.findProperty(\"Max Samples\") : null;\n"
        "    if (!_iProp) throw new Error(\"iray_samples: Iray 'Max Samples' property not found\");\n"
        "    if (_iProp.isClamped && _iProp.isClamped()\n"
        "        && (iraySamples < _iProp.getMin() || iraySamples > _iProp.getMax()))\n"
        "      throw new Error(\"iray_samples \" + iraySamples + \" is outside the supported range \"\n"
        "        + _iProp.getMin() + \"..\" + _iProp.getMax());\n"
        "    _prevMaxSamples = Number(_iProp.getValue());\n"
        "    _maxSamplesProp = _iProp;\n"
        "    _iProp.setValue(iraySamples);\n"
        "    var _applied = Number(_iProp.getValue());\n"
        "    if (_applied !== iraySamples) {\n"
        "      _iProp.setValue(_prevMaxSamples);\n"
        "      throw new Error(\"iray_samples readback mismatch: requested \" + iraySamples + \", got \" + _applied);\n"
        "    }\n"
        "    irayReadback = {\n"
        "      requested: iraySamples, applied: _applied, previous: _prevMaxSamples, restored: false,\n"
        "      provenance: {kind: \"live_readback\", source: \"DzIrayRenderer.getPropertyHolder().findProperty('Max Samples')\"}\n"
        "    };\n"
        "  }\n\n";

    // ── Render ────────────────────────────────────────────────────────────
    // doRender()'s own return value is undocumented in the SDK (no
    // "Returns:" section at all) and was observed live to report success
    // even for a render the user cancelled mid-progress via the DAZ Studio
    // UI. renderFinished(bool succeeded) is the SDK's explicit, named
    // completion signal -- SceneEventBroker.cpp already relies on it as the
    // "guaranteed exit path" that fires correctly across error/cancel cases
    // -- so capture it directly instead of hardcoding success.
    script +=
        "  var renderSucceeded = null;\n"
        "  function _onRenderFinished(succeeded) { renderSucceeded = succeeded; }\n";
    script += bindRenderFinishedJs("renderMgr");
    script +=
        "  try {\n"
        "    renderMgr.doRender(opts);\n"
        "    if (!_finishedBound && renderSucceeded === null) renderSucceeded = true;\n"
        "  } finally {\n";
    script += unbindRenderFinishedJs;
    script +=
        "    if (_maxSamplesProp) {\n"
        "      _maxSamplesProp.setValue(_prevMaxSamples);\n"
        "      irayReadback.restored = Number(_maxSamplesProp.getValue()) === _prevMaxSamples;\n"
        "    }\n"
        "  }\n";
    // renderFinished(true) also fires for a render that couldn't write its
    // file (alaz: unmapped drive, viewport engine), so check the output.
    script += requireRenderOutputJs;
    script +=
        "  if (renderSucceeded === true) _requireRenderOutput(outputPath);\n"
        "  return {success: renderSucceeded === true, output_path: outputPath, engine: engineReadback,"
        " iray_samples: irayReadback};\n"
        "})();\n";

    return script;
}

// Builds the DazScript that loops a frame range, moving the scene's playhead
// with Scene.setFrame() (confirmed in dzscene.h) and rendering one file per
// frame. outputPattern must contain the literal token "{frame}", which is
// replaced with the frame number zero-padded to framePadding digits.
//
// Restores the original current frame after the loop so the render doesn't
// leave the scene's timeline position mutated.
QString buildAnimationRenderScript(
    const QString& outputPattern,
    int startFrame, int endFrame, int framePadding,
    int width, int height,
    const QString& camera,
    const QString& engine,
    const QString& frameReportFile)
{
    QString outputPatternEsc = QString::fromStdString(
        JsonStd::escape(JsonStd::qstrToStd(outputPattern)));
    QString frameReportEsc = frameReportFile.isEmpty() ? QString("null")
        : "\"" + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(frameReportFile))) + "\"";
    QString cameraEsc = camera.isEmpty() ? QString("null")
        : "\"" + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(camera))) + "\"";
    QString engineEsc = engine.isEmpty() ? QString("null")
        : "\"" + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(engine))) + "\"";

    QString script;
    script += "(function() {\n";
    script += "  var outputPattern = \"" + outputPatternEsc + "\";\n";
    script += "  var startFrame = " + QString::number(startFrame) + ";\n";
    script += "  var endFrame = " + QString::number(endFrame) + ";\n";
    script += "  var framePadding = " + QString::number(framePadding) + ";\n";
    script += "  var cameraName = " + cameraEsc + ";\n";
    script += "  var engineName = " + engineEsc + ";\n";
    script += "  var width = " + QString::number(width) + ";\n";
    script += "  var height = " + QString::number(height) + ";\n";
    script += "  var frameReportFile = " + frameReportEsc + ";\n\n";

    script +=
        "  function padFrame(n, width) {\n"
        "    var s = String(n);\n"
        "    while (s.length < width) s = \"0\" + s;\n"
        "    return s;\n"
        "  }\n\n";

    // ── Frame progress report ─────────────────────────────────────────────
    // On Studio 6 print() is shimmed into an array (see runDazScript), so the
    // [DAZPY_FRAME] marker below never reaches onMessagePosted while the job
    // runs. The server-owned JSONL report is read live by polling workers
    // instead. The whole event list is rewritten each frame (the same
    // pattern the report-file tests use) rather than relying on an append
    // open mode. Best effort: a failed write must never fail the render.
    script +=
        "  var frameEvents = \"\";\n"
        "  function reportFrame(frame, total) {\n"
        "    if (!frameReportFile) return;\n"
        "    try {\n"
        "      frameEvents += JSON.stringify({type: \"progress\", value: (frame - 1) / total,\n"
        "        current: frame - 1, total: total, frame: frame, phase: \"rendering\",\n"
        "        message: \"Rendering frame \" + frame + \" of \" + total}) + \"\\n\";\n"
        "      var rf = new DzFile(frameReportFile);\n"
        "      if (rf.open(DzFile.WriteOnly)) { rf.write(frameEvents); rf.close(); }\n"
        "    } catch (e) {}\n"
        "  }\n\n";

    // ── Configure render options (shared across all frames) ───────────────
    script +=
        "  var renderMgr = App.getRenderMgr();\n"
        "  var opts = renderMgr.getRenderOptions();\n"
        "  opts.renderImgToId = 2;\n";  // DirectToFile
    script +=
        "  if (width > 0) opts.imageSize = new QSize(width, height);\n";
    script +=
        "  if (cameraName) {\n"
        "    var cam = Scene.findCameraByLabel(cameraName);\n"
        "    if (!cam) return {success: false, error: 'Camera not found: ' + cameraName};\n"
        "    opts.camera = cam;\n"
        "    var viewportMgr = MainWindow.getViewportMgr();\n"
        "    var activeViewport = viewportMgr ? viewportMgr.getActiveViewport() : null;\n"
        "    if (activeViewport) activeViewport.get3DViewport().setCamera(cam);\n"
        "  }\n";
    script +=
        "  var engineReadback = null;\n"
        "  if (engineName) {\n"
        "    var requestedEngine = engineName.toLowerCase();\n"
        "    var engineMap = {\"iray\": \"DzIrayRenderer\", \"filament\": \"DzFilamentRenderer\"};\n"
        "    var requestedClass = engineMap[requestedEngine];\n"
        "    if (requestedEngine === \"viewport\") {\n"
        "      opts.renderType = opts.ScreenShot;\n"
        "    } else {\n"
        "      if (!requestedClass) throw new Error(\"Unknown render engine request: \" + requestedEngine);\n"
        "      var requestedRenderer = renderMgr.findRenderer(requestedClass);\n"
        "      if (!requestedRenderer) throw new Error(\"Render engine is not registered: \" + requestedClass);\n"
        "      renderMgr.setActiveRenderer(requestedRenderer);\n"
        "      opts.renderType = opts.Software;\n"
        "    }\n"
        "    opts.applyChanges();\n"
        "    var effectiveType = Number(opts.renderType);\n"
        "    var effectiveRenderer = renderMgr.getActiveRenderer();\n"
        "    var effectiveClass = effectiveRenderer ? String(effectiveRenderer.className()) : null;\n"
        "    var effectiveName = effectiveRenderer ? String(effectiveRenderer.getName()) : null;\n"
        "    var exactMatch = requestedEngine === \"viewport\"\n"
        "      ? effectiveType === Number(opts.ScreenShot)\n"
        "      : effectiveType === Number(opts.Software) && effectiveClass === requestedClass;\n"
        "    if (!exactMatch) throw new Error(\"Render engine readback mismatch for request: \" + requestedEngine);\n"
        "    var typeName = effectiveType === Number(opts.ScreenShot) ? \"ScreenShot\"\n"
        "      : effectiveType === Number(opts.HardwareAssisted) ? \"HardwareAssisted\"\n"
        "      : effectiveType === Number(opts.Software) ? \"Software\" : null;\n"
        "    engineReadback = {\n"
        "      selector_schema: 1,\n"
        "      status: requestedEngine === \"iray\" ? \"verified_iray\" : \"verified_non_iray\",\n"
        "      engine: requestedEngine === \"iray\" ? \"iray\" : (requestedEngine === \"viewport\" ? \"viewport_gl\" : \"other_non_iray\"),\n"
        "      method: \"render_settings_engine_selector\",\n"
        "      reason: requestedEngine === \"iray\" ? null : \"non_iray_engine\",\n"
        "      render_type: {raw: effectiveType, name: typeName, provenance: {kind: \"live_readback\", source: \"DzRenderOptions.renderType\"}},\n"
        "      active_renderer: {class_name: effectiveClass, name: effectiveName, provenance: {kind: \"live_readback\", source: \"DzRenderMgr.getActiveRenderer\"}}\n"
        "    };\n"
        "  }\n\n";

    // ── Render each frame ───────────────────────────────────────────────────
    // doRender()'s own return value is undocumented in the SDK (no
    // "Returns:" section at all) and was observed live to report success
    // even for a render the user cancelled mid-progress via the DAZ Studio
    // UI. renderFinished(bool succeeded) is the SDK's explicit, named
    // completion signal -- SceneEventBroker.cpp already relies on it as the
    // "guaranteed exit path" that fires correctly across error/cancel cases
    // -- so capture it per frame instead of hardcoding success.
    script +=
        "  var originalFrame = Scene.getFrame();\n"
        "  var outputPaths = [];\n"
        "  var allSucceeded = true;\n"
        "  var frameSucceeded = null;\n"
        "  function _onRenderFinished(succeeded) { frameSucceeded = succeeded; }\n";
    script += requireRenderOutputJs;
    script += bindRenderFinishedJs("renderMgr");
    script +=
        "  try {\n"
        "    for (var f = startFrame; f <= endFrame; f++) {\n"
        "      Scene.setFrame(f);\n"
        "      var framePath = outputPattern.replace('{frame}', padFrame(f, framePadding));\n"
        "      opts.renderImgFilename = framePath;\n"
        "      frameSucceeded = null;\n"
        "      reportFrame(f - startFrame + 1, endFrame - startFrame + 1);\n"
        "      print(\"[DAZPY_FRAME] \" + (f - startFrame + 1) + \"/\" + (endFrame - startFrame + 1));\n"
        "      renderMgr.doRender(opts);\n"
        "      if (_finishedBound && frameSucceeded !== true) allSucceeded = false;\n"
        "      if (allSucceeded) _requireRenderOutput(framePath);\n"
        "      outputPaths.push(framePath);\n"
        "    }\n"
        "  } finally {\n";
    script += unbindRenderFinishedJs;
    // Restore the playhead here too when a frame throws (e.g. wrote no file).
    script +=
        "    Scene.setFrame(originalFrame);\n"
        "  }\n\n";

    script +=
        "  return {success: allSucceeded, frame_count: outputPaths.length, output_paths: outputPaths, engine: engineReadback};\n"
        "})();\n";

    return script;
}

} // namespace RenderScriptBuilder
