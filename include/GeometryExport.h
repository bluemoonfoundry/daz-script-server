#pragma once
// Fork-only (BlackByteDE): POST /geometry/frames — deformed figure vertices for
// a list of frames as a binary float32 payload. Kept in its own files so the
// upstream sources only gain a handful of wiring lines.
//
// Request (JSON):
//   {
//     "frames":     [int, ...],          required, non-empty
//     "node":       "name or label",     optional; default = first figure
//                                        (DzSkeleton without follow target)
//     "indices":    [int, ...],          optional vertex subset
//     "surfaces":   ["Face", ...],       optional; adds every vertex of the
//                                        surfaces' facets to the subset
//     "bones":      ["lHand", ...],      optional; world-space bone origins
//     "resolution": "base" | "current",  optional, default "base"; "base"
//                                        switches Resolution Level to Base
//                                        only if the cached mesh is not
//                                        already the base cage (rare; ~1 s)
//     "sceneUpdate": true                optional; false skips the final
//                                        Scene update (~130 ms on a dressed
//                                        figure) — for back-to-back calls,
//                                        let only the last one update
//   }
//   Without indices/surfaces all vertices are returned.
//
// Response 200 (application/octet-stream, little-endian):
//   char    magic[4]   "DZGF"
//   uint32  version    1
//   uint32  numFrames
//   uint32  numVerts   vertices per frame (subset size if a subset was given)
//   uint32  numBones
//   uint32  flags      bit 0: index section present
//   uint32  reserved[2]
//   int32   frames[numFrames]
//   uint32  indices[numVerts]                    only if flags & 1
//   float32 verts[numFrames][numVerts][3]
//   float32 bones[numFrames][numBones][3]
// Errors are the usual JSON error body.
//
// Per frame only the figure is evaluated (setFrame + forceCacheUpdate), not the
// whole scene; the original frame and resolution level are restored afterwards
// followed by one Scene update (unless sceneUpdate is false).

#include <QtCore/qobject.h>
#include <QtCore/qbytearray.h>
#include "DzScriptServerPane.h"  // HttpResult + its metatype, IRequestHandler

// Lives on the main thread; called via BlockingQueuedConnection.
class GeometryExporter : public QObject {
	Q_OBJECT
public:
	explicit GeometryExporter(QObject* parent = nullptr) : QObject(parent) {}
	// 200 → binary payload, anything else → JSON error body.
	Q_INVOKABLE HttpResult exportFrames(const QByteArray& jsonBody);
};

class GeometryFramesHandler : public IRequestHandler {
public:
	// Must be constructed on the main thread (the exporter's thread affinity).
	GeometryFramesHandler();
	~GeometryFramesHandler() override;
	void handle(HttpContext& ctx) override;
private:
	GeometryExporter* m_pExporter;
};
