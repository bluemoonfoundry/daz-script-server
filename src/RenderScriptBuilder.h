#pragma once
// DazScript generated for the render routes (POST /render, /render/batch,
// /render/animation). Pure string building with no pane state and no DAZ SDK
// calls; the scripts run later on the main thread via processNextAsyncRequest().
#include <string>
#include <QtCore/qlist.h>
#include <QtCore/qstring.h>
#include <QtCore/qvariant.h>

namespace RenderScriptBuilder {

struct FigureSpec {
    QString     name;
    QVariantMap morphs;
};

// Reads an optional "iray_samples" field from a request object. Absent keeps
// *out (the caller's default); 0 means "use the scene's Iray setting".
// Negative or non-integer values fail with *err set.
bool readIraySamples(const QVariantMap& m, int* out, std::string* err);

// Single still render: validate figures, optionally reset morphs, apply
// morphs, configure render options, render to outputPath.
QString buildRenderScript(
    const QString& outputPath,
    int width, int height,
    const QString& camera,
    const QString& engine,
    int iraySamples,
    bool resetMorphs,
    const QList<FigureSpec>& figures);

// Frame-range render: one file per frame from outputPattern ("{frame}" token,
// zero-padded to framePadding), with a per-frame report written to
// frameReportFile when set. Restores the scene's current frame afterwards.
QString buildAnimationRenderScript(
    const QString& outputPattern,
    int startFrame, int endFrame, int framePadding,
    int width, int height,
    const QString& camera,
    const QString& engine,
    const QString& frameReportFile);

} // namespace RenderScriptBuilder
