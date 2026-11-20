#pragma once
// Handlers for the artifact routes (5d6f.7), on raw httplib worker threads.
//
// They read a mutex-protected copy of the job's output manifest and use C
// stdio for file access (ArtifactFile), never DAZ or GUI objects. URL segments
// are IDs, never paths: the only file that can be opened is one the job itself
// declared, and only inside the allowed artifact folders (ArtifactRoots).
// Thumbnails (?thumbnail=<px>) decode on the main thread, so they stay in
// DzScriptServerPane::serveArtifactThumbnail(), which uses idsValid() and
// openDeclared() from here.

#include <QtCore/qstring.h>
#include <QtCore/qstringlist.h>
#include <QtCore/qglobal.h>
#include <cstdio>

namespace httplib { struct Request; struct Response; }
class AsyncRequestManager;
class ArtifactRoots;

namespace ArtifactRoutes {

// Both URL IDs are 1-64 chars of [A-Za-z0-9_-]; writes a 400 otherwise.
bool idsValid(const httplib::Request& req, httplib::Response& res);

// GET /artifacts/{id}: the job's declared outputs plus file metadata.
void list(AsyncRequestManager& mgr, const ArtifactRoots& roots,
          const QStringList& thumbnailExts,
          const httplib::Request& req, httplib::Response& res);

// Resolve {id}/{artifact_id} to the declared file and open it. On failure the
// error response is already written and false is returned; on success the
// caller owns *file and must fclose() it.
bool openDeclared(AsyncRequestManager& mgr, const ArtifactRoots& roots,
                  const httplib::Request& req, httplib::Response& res,
                  QString* path, FILE** file, qint64* size, qint64* mtime = 0);

// GET /artifacts/{id}/{artifact_id}: stream one declared output (Range, HEAD).
void serve(AsyncRequestManager& mgr, const ArtifactRoots& roots,
           const httplib::Request& req, httplib::Response& res);

} // namespace ArtifactRoutes
