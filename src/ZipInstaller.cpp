#include "ZipInstaller.h"

#include "JsonStd.h"
#include "PortableFs.h"
#include "miniz.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QUuid>

// QRegularExpression is Qt5+; Qt 4.8 (SDK4 build) only has the older QRegExp.
#if DAZ_SDK_MAJOR_VERSION >= 6
#include <QRegularExpression>
#else
#include <QRegExp>
#endif

namespace {

// Zip entries always use forward slashes per the zip spec, but a malicious
// entry could smuggle a backslash to escape on Windows -- treat both as path
// separators when validating.
bool isSafeRelativePath(const QString &entryName)
{
	if (entryName.isEmpty())
		return false;

	// Absolute paths: leading slash, or a Windows drive letter (e.g. "C:\...").
	if (entryName.startsWith('/') || entryName.startsWith('\\'))
		return false;
	if (entryName.size() >= 2 && entryName.at(1) == ':')
		return false;

#if DAZ_SDK_MAJOR_VERSION >= 6
	const QStringList segments = entryName.split(QRegularExpression("[/\\\\]"), Qt::SkipEmptyParts);
#else
	const QStringList segments = entryName.split(QRegExp("[/\\\\]"), QString::SkipEmptyParts);
#endif
	for (const QString &segment : segments) {
		if (segment == QString::fromLatin1(".."))
			return false;
	}
	return true;
}

// Unix symlink detection: when an entry was written by a Unix zip tool, the
// upper 16 bits of m_external_attr hold the st_mode value, whose file-type
// nibble (S_IFMT) is S_IFLNK (0xA000) for a symlink.
bool isSymlinkEntry(const mz_zip_archive_file_stat &stat)
{
	const mz_uint32 unixMode = stat.m_external_attr >> 16;
	return (unixMode & 0xF000) == 0xA000;
}

// Threaded through mz_zip_reader_extract_to_callback: writes decompressed
// bytes to destFile while independently re-counting them against the caps,
// so a header that under-reports an entry's real size cannot smuggle a
// zip bomb past the earlier header-based pre-check.
struct LiveExtractContext {
	QFile   *destFile        = nullptr;
	qint64   entryBytesSoFar = 0;
	qint64  *totalBytesSoFar = nullptr;  // shared running total across the whole archive
	qint64   entryLimit      = 0;
	qint64   totalLimit      = 0;
	bool     limitExceeded   = false;
};

size_t liveExtractWriteCallback(void *pOpaque, mz_uint64 /*fileOfs*/, const void *pBuf, size_t n)
{
	auto *ctx = static_cast<LiveExtractContext *>(pOpaque);

	ctx->entryBytesSoFar += static_cast<qint64>(n);
	*ctx->totalBytesSoFar += static_cast<qint64>(n);
	if (ctx->entryBytesSoFar > ctx->entryLimit || *ctx->totalBytesSoFar > ctx->totalLimit) {
		ctx->limitExceeded = true;
		return 0;  // any return value != n aborts extraction immediately
	}

	const qint64 written = ctx->destFile->write(static_cast<const char *>(pBuf), static_cast<qint64>(n));
	if (written != static_cast<qint64>(n)) {
		ctx->limitExceeded = false;  // not a limit failure, but still must abort
		return 0;
	}
	return n;
}

// RAII guard so every early-return path below still calls mz_zip_reader_end().
class ZipReaderGuard {
public:
	explicit ZipReaderGuard(mz_zip_archive *zip) : m_zip(zip) {}
	~ZipReaderGuard() { mz_zip_reader_end(m_zip); }
	ZipReaderGuard(const ZipReaderGuard &) = delete;
	ZipReaderGuard &operator=(const ZipReaderGuard &) = delete;

private:
	mz_zip_archive *m_zip;
};

// QUuid::WithoutBraces is Qt5.11+; Qt 4.8's QUuid::toString() always
// includes the surrounding braces, so strip them manually.
QString newUuidNoBraces() {
#if DAZ_SDK_MAJOR_VERSION >= 6
	return QUuid::createUuid().toString(QUuid::WithoutBraces);
#else
	const QString withBraces = QUuid::createUuid().toString();
	return withBraces.mid(1, withBraces.length() - 2);
#endif
}

}  // namespace

ZipInstaller::ZipInstaller(QString packagesDir, Limits limits)
	: m_packagesDir(std::move(packagesDir))
	, m_limits(limits)
{
}

ZipInstaller::Result ZipInstaller::install(const QString &zipPath) const
{
	Result result;

	const StageResult staged = extractToStaging(zipPath);
	if (!staged.success) {
		result.errorMessage = staged.errorMessage;
		return result;
	}

	const QString finalDir = QDir(m_packagesDir).filePath(staged.packageId);
	if (QFileInfo(finalDir).exists()) {
		PortableFs::removeRecursively(staged.stagingDir);
		result.errorMessage = QString::fromLatin1(
			"Package '%1' is already installed; reinstall is not handled by this installer").arg(staged.packageId);
		return result;
	}

	const CommitResult committed = commit(staged.packageId, staged.stagingDir);
	if (!committed.success) {
		result.errorMessage = committed.errorMessage;
		return result;
	}

	result.success = true;
	result.packageId = staged.packageId;
	result.finalPackageDir = committed.finalPackageDir;
	return result;
}

ZipInstaller::StageResult ZipInstaller::extractToStaging(const QString &zipPath) const
{
	StageResult result;

	if (!QFileInfo(zipPath).exists()) {
		result.errorMessage = QString::fromLatin1("Archive not found: %1").arg(zipPath);
		return result;
	}

	QDir packagesDir(m_packagesDir);
	if (!packagesDir.mkpath(QString::fromLatin1("."))) {
		result.errorMessage = QString::fromLatin1("Could not create packages directory: %1").arg(m_packagesDir);
		return result;
	}

	const QString stagingRoot = packagesDir.filePath(QString::fromLatin1(".staging/") + newUuidNoBraces());
	QDir stagingDir(stagingRoot);
	if (!stagingDir.mkpath(QString::fromLatin1("."))) {
		result.errorMessage = QString::fromLatin1("Could not create staging directory: %1").arg(stagingRoot);
		return result;
	}

	auto failAndCleanStaging = [&](const QString &message) -> StageResult {
		PortableFs::removeRecursively(stagingRoot);
		result.success = false;
		result.errorMessage = message;
		return result;
	};

	mz_zip_archive zip;
	memset(&zip, 0, sizeof(zip));
	if (!mz_zip_reader_init_file(&zip, zipPath.toUtf8().constData(), 0)) {
		return failAndCleanStaging(QString::fromLatin1("Not a valid zip archive: %1").arg(zipPath));
	}
	ZipReaderGuard zipGuard(&zip);

	const mz_uint numFiles = mz_zip_reader_get_num_files(&zip);
	if (static_cast<int>(numFiles) > m_limits.maxEntryCount) {
		return failAndCleanStaging(QString::fromLatin1("Archive has too many entries (%1 > %2)")
			.arg(numFiles).arg(m_limits.maxEntryCount));
	}

	qint64 liveTotalBytes = 0;

	for (mz_uint i = 0; i < numFiles; ++i) {
		mz_zip_archive_file_stat stat;
		if (!mz_zip_reader_file_stat(&zip, i, &stat)) {
			return failAndCleanStaging(QString::fromLatin1("Could not read archive entry %1").arg(i));
		}

		if (stat.m_is_encrypted) {
			return failAndCleanStaging(QString::fromLatin1("Encrypted entries are not allowed: %1")
				.arg(QString::fromUtf8(stat.m_filename)));
		}
		if (!stat.m_is_supported) {
			return failAndCleanStaging(QString::fromLatin1("Unsupported compression method for entry: %1")
				.arg(QString::fromUtf8(stat.m_filename)));
		}

		const QString entryName = QString::fromUtf8(stat.m_filename);
		if (!isSafeRelativePath(entryName)) {
			return failAndCleanStaging(QString::fromLatin1("Archive entry has an unsafe path: %1").arg(entryName));
		}
		if (isSymlinkEntry(stat)) {
			return failAndCleanStaging(QString::fromLatin1("Symlink entries are not allowed: %1").arg(entryName));
		}

		// Header-based pre-check: cheap, but a crafted header can lie -- the
		// real enforcement is the live recount in liveExtractWriteCallback below.
		if (stat.m_uncomp_size > static_cast<mz_uint64>(m_limits.maxEntryUncompressedBytes)) {
			return failAndCleanStaging(QString::fromLatin1("Archive entry exceeds the per-entry size limit: %1").arg(entryName));
		}
		if (stat.m_uncomp_size > 0 && stat.m_comp_size == 0) {
			return failAndCleanStaging(QString::fromLatin1("Archive entry has an implausible size (possible zip bomb): %1").arg(entryName));
		}
		if (stat.m_comp_size > 0) {
			const qint64 ratio = static_cast<qint64>(stat.m_uncomp_size / stat.m_comp_size);
			if (ratio > m_limits.maxCompressionRatio) {
				return failAndCleanStaging(QString::fromLatin1("Archive entry's compression ratio is implausible (possible zip bomb): %1").arg(entryName));
			}
		}

		if (stat.m_is_directory) {
			if (!stagingDir.mkpath(entryName)) {
				return failAndCleanStaging(QString::fromLatin1("Could not create directory for entry: %1").arg(entryName));
			}
			continue;
		}

		const QString destPath = stagingDir.filePath(entryName);
		const QFileInfo destInfo(destPath);
		if (!QDir().mkpath(destInfo.absolutePath())) {
			return failAndCleanStaging(QString::fromLatin1("Could not create parent directory for entry: %1").arg(entryName));
		}

		QFile destFile(destPath);
		if (!destFile.open(QIODevice::WriteOnly)) {
			return failAndCleanStaging(QString::fromLatin1("Could not write extracted entry: %1").arg(entryName));
		}

		LiveExtractContext ctx;
		ctx.destFile = &destFile;
		ctx.totalBytesSoFar = &liveTotalBytes;
		ctx.entryLimit = m_limits.maxEntryUncompressedBytes;
		ctx.totalLimit = m_limits.maxTotalUncompressedBytes;

		const mz_bool extractOk = mz_zip_reader_extract_to_callback(&zip, i, liveExtractWriteCallback, &ctx, 0);
		destFile.close();

		if (!extractOk) {
			if (ctx.limitExceeded) {
				return failAndCleanStaging(QString::fromLatin1("Archive exceeded size limits during extraction (zip bomb defense): %1").arg(entryName));
			}
			return failAndCleanStaging(QString::fromLatin1("Failed to extract archive entry: %1").arg(entryName));
		}
	}

	// manifest.json is required at the extracted root and must name the
	// package id this install will land under.
	const QString manifestPath = stagingDir.filePath(QString::fromLatin1("manifest.json"));
	QFile manifestFile(manifestPath);
	if (!manifestFile.open(QIODevice::ReadOnly)) {
		return failAndCleanStaging(QString::fromLatin1("Archive is missing manifest.json at its root"));
	}
	const QByteArray manifestBytes = manifestFile.readAll();
	manifestFile.close();

	QVariantMap manifest;
	std::string parseError;
	if (!JsonStd::parseObject(manifestBytes, manifest, parseError)) {
		return failAndCleanStaging(QString::fromLatin1("manifest.json is not valid JSON: %1").arg(QString::fromStdString(parseError)));
	}

	const QString packageId = manifest.value(QString::fromLatin1("id")).toString();
#if DAZ_SDK_MAJOR_VERSION >= 6
	static const QRegularExpression idPattern(QString::fromLatin1("^[A-Za-z0-9_-]+$"));
	const bool idMatches = idPattern.match(packageId).hasMatch();
#else
	static const QRegExp idPattern(QString::fromLatin1("^[A-Za-z0-9_-]+$"));
	const bool idMatches = idPattern.exactMatch(packageId);
#endif
	if (packageId.isEmpty() || !idMatches) {
		return failAndCleanStaging(QString::fromLatin1("manifest.json 'id' field must be a non-empty string matching [A-Za-z0-9_-]+"));
	}

	result.success = true;
	result.packageId = packageId;
	result.version = manifest.value(QString::fromLatin1("version")).toString();
	result.stagingDir = stagingRoot;
	return result;
}

ZipInstaller::CommitResult ZipInstaller::commit(const QString &packageId, const QString &stagingDir) const
{
	CommitResult result;
	QDir packagesDir(m_packagesDir);
	const QString finalDir = packagesDir.filePath(packageId);

	if (QFileInfo(finalDir).exists()) {
		// Overwrite-by-id: move the existing install aside, swap the staged
		// one into place, then discard the displaced one -- so a rename
		// failure on either leg leaves a recognizable `.old-<uuid>` directory
		// behind rather than a half-replaced or lost package.
		const QString displacedDir = packagesDir.filePath(
			packageId + QString::fromLatin1(".old-") + newUuidNoBraces());
		if (!QDir().rename(finalDir, displacedDir)) {
			result.errorMessage = QString::fromLatin1(
				"Could not move aside the existing package to replace it: %1").arg(finalDir);
			return result;
		}
		if (!QDir().rename(stagingDir, finalDir)) {
			QDir().rename(displacedDir, finalDir);  // best-effort restore of the previous install
			result.errorMessage = QString::fromLatin1("Could not move staged package into place: %1").arg(finalDir);
			return result;
		}
		PortableFs::removeRecursively(displacedDir);
	} else if (!QDir().rename(stagingDir, finalDir)) {
		result.errorMessage = QString::fromLatin1("Could not move staged package into place: %1").arg(finalDir);
		return result;
	}

	result.success = true;
	result.finalPackageDir = finalDir;
	return result;
}
