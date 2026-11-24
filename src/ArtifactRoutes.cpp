// GET /artifacts/{id} and GET /artifacts/{id}/{artifact_id} (file download).
// Split out of DzScriptServerPane.cpp (x7ul.32); see ArtifactRoutes.h.
// httplib (winsock2.h) must come before any header that may pull in windows.h.
#include "RouteUtil.h"
#include "ArtifactRoutes.h"
#include "ArtifactFile.h"
#include "ArtifactRoots.h"
#include "ArtifactThumbnail.h"
#include "AsyncRequestManager.h"
#include "JsonStd.h"

#include <QtCore/qvariant.h>
#include <cstdio>

namespace ArtifactRoutes {

bool idsValid(const httplib::Request& req, httplib::Response& res)
{
	static const char* const kNames[] = { "", "job_id", "artifact_id" };
	for (size_t i = 1; i < req.matches.size() && i < 3; ++i) {
		const std::string v = req.matches[i].str();
		if (!ArtifactFile::isValidId(v.c_str(), v.size())) {
			respondError(res, ErrorCode::INVALID_FIELD,
				std::string(kNames[i]) + " must be 1-64 characters of A-Z, a-z, 0-9, '-' or '_'");
			return false;
		}
	}
	return true;
}

// GET /artifacts/:job_id — the job's declared outputs plus file metadata.
void list(AsyncRequestManager& mgr, const ArtifactRoots& roots,
                          const QStringList& thumbnailExts,
                          const httplib::Request& req, httplib::Response& res)
{
	if (!idsValid(req, res)) return;
	const std::string jobId = req.matches[1].str();

	QVariantList entries;
	QString      status;
	if (!mgr.artifactManifest(jobId, entries, status)) {
		respondError(res, ErrorCode::REQUEST_NOT_FOUND, jobId);
		return;
	}

	QVariantList artifacts;
	for (int i = 0; i < entries.size(); ++i) {
		QVariantMap entry = entries[i].toMap();
		const QString path = entry.value("path").toString();
		const qint64  size = ArtifactFile::sizeOf(path, &roots);
		entry.insert("available", size >= 0);
		entry.insert("size", size >= 0 ? QVariant(size) : QVariant());
		entry.insert("content_type", QString::fromLatin1(ArtifactFile::contentTypeFor(path)));
		entry.insert("filename", ArtifactFile::baseName(path));
		entry.insert("thumbnail_supported",
			size >= 0 && size <= ArtifactThumbnail::kMaxSourceBytes
			&& ArtifactThumbnail::extensionIn(path, thumbnailExts));
		artifacts.append(entry);
	}

	QVariantMap body;
	body.insert("success", true);
	body.insert("request_id", QString::fromStdString(jobId));
	body.insert("status", status);
	body.insert("count", artifacts.size());
	body.insert("artifacts", artifacts);
	res.status = 200;
	res.set_content(JsonStd::variantToJson(QVariant(body)), "application/json");
}

// Resolve :job_id/:artifact_id to the declared file and open it. On failure
// the error response is already written and false is returned; on success the
// caller owns *file and must fclose() it.
bool openDeclared(AsyncRequestManager& mgr, const ArtifactRoots& roots,
                  const httplib::Request& req,
                  httplib::Response& res, QString* path, FILE** file,
                  qint64* size, qint64* mtime)
{
	if (!idsValid(req, res)) return false;
	const std::string jobId      = req.matches[1].str();
	const std::string artifactId = req.matches[2].str();

	switch (mgr.findArtifact(jobId, artifactId, *path)) {
	case AsyncRequestManager::ARTIFACT_JOB_NOT_FOUND:
		respondError(res, ErrorCode::REQUEST_NOT_FOUND, jobId);
		return false;
	case AsyncRequestManager::ARTIFACT_NOT_DECLARED:
		respondError(res, ErrorCode::ARTIFACT_NOT_FOUND, jobId + "/" + artifactId);
		return false;
	case AsyncRequestManager::ARTIFACT_FOUND:
		break;
	}

	switch (ArtifactFile::openForRead(*path, file, size, mtime, &roots)) {
	case ArtifactFile::OPEN_OK:
		return true;
	case ArtifactFile::OPEN_OUTSIDE_ROOTS:
		respondError(res, ErrorCode::ARTIFACT_OUTSIDE_ROOTS,
			"the declared file's real path is outside the allowed artifact folders "
			"(server pane: Artifact Folders)");
		return false;
	case ArtifactFile::OPEN_PATH_REJECTED:
		respondError(res, ErrorCode::ARTIFACT_UNAVAILABLE, "declared path is not an absolute file path");
		return false;
	case ArtifactFile::OPEN_NOT_REGULAR:
		respondError(res, ErrorCode::ARTIFACT_UNAVAILABLE, "declared path is not a regular file");
		return false;
	case ArtifactFile::OPEN_MISSING:
	default:
		respondError(res, ErrorCode::ARTIFACT_UNAVAILABLE, "declared file does not exist or cannot be read");
		return false;
	}
}

// GET /artifacts/:job_id/:artifact_id — stream one declared output. httplib
// answers Range requests (206 / 416) and HEAD from the sized content provider.
void serve(AsyncRequestManager& mgr, const ArtifactRoots& roots,
           const httplib::Request& req,
           httplib::Response& res)
{
	QString path;
	FILE*   file = 0;
	qint64  size = 0;
	if (!openDeclared(mgr, roots, req, res, &path, &file, &size)) return;

	// Leave res.status unset: httplib then picks 200, or 206 for a Range
	// request (and 416 for an unsatisfiable one). An explicit 200 would make
	// it ignore the Range header and send the whole file.
	const QByteArray disposition = ArtifactFile::contentDisposition(path);
	res.set_header("Accept-Ranges", "bytes");
	res.set_header("Content-Disposition", disposition.constData());
	res.set_header("Cache-Control", "private, no-store");
	res.set_header("X-Content-Type-Options", "nosniff");
	res.set_content_provider(
		static_cast<size_t>(size), ArtifactFile::contentTypeFor(path),
		[file](size_t offset, size_t length, httplib::DataSink& sink) {
			if (!ArtifactFile::seek(file, static_cast<qint64>(offset))) return false;
			char buf[64 * 1024];
			while (length > 0) {
				const size_t want = length < sizeof(buf) ? length : sizeof(buf);
				const size_t got  = std::fread(buf, 1, want, file);
				if (got == 0) return false;   // file shrank or read error
				if (!sink.write(buf, got)) return false;
				length -= got;
			}
			return true;
		},
		[file](bool) { std::fclose(file); });
}

} // namespace ArtifactRoutes
