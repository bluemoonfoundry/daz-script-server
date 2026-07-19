#pragma once

#include <QString>

// Hardened installer for .dzpkg package archives (Package Runner epic,
// daz-script-server-5sw), ported from daz-python-bridge's ZipInstaller
// (originally built for daz-python-bridge-sop.3's plugin zips -- the
// hardening is domain-agnostic, only the "plugin" vocabulary changed to
// "package" here).
//
// Defends the filesystem against a hostile archive: path traversal
// (zip-slip), symlink entries, and zip-bomb resource exhaustion. Does NOT
// defend against a malicious package's actual Python code -- arbitrary code
// execution is inherent to running a third-party package and is a separate
// trust-model concern for community distribution, not solved by extraction
// hardening.
//
// Every install extracts into a fresh staging directory under
// <packagesDir>/.staging/<uuid>/. The live packages directory is only ever
// touched once by an atomic rename of that staging directory into
// <packagesDir>/<id>/, and only after every entry has been validated AND
// fully, successfully extracted, and manifest.json has been checked. Any
// rejection or extraction failure removes the staging directory and leaves
// the live packages dir untouched.
//
// Byte/entry-count limits are enforced twice: once cheaply from the zip
// central directory's header fields (fast rejection of obviously-bad
// archives), and again live, counted from the bytes actually written during
// decompression -- a crafted header cannot lie its way past the second
// check, which is what actually defends against zip bombs.
//
// install() refuses to touch an existing <packagesDir>/<id> --
// reinstalling over one (e.g. opening a newer version of an already-opened
// package) is the caller's job via extractToStaging()/commit(): extract and
// learn the package id without touching the live directory, decide what to
// do about a same-id collision, *then* commit.
class ZipInstaller {
public:
	struct Limits {
		qint64 maxTotalUncompressedBytes = 200LL * 1024 * 1024;  // whole archive
		qint64 maxEntryUncompressedBytes = 100LL * 1024 * 1024;  // any single entry
		int    maxEntryCount             = 5000;
		// Rejects entries whose claimed uncompressed:compressed ratio is
		// absurd even when both sizes are individually under the caps above
		// (the classic zip-bomb shape: a tiny compressed entry inflating to
		// something enormous).
		qint64 maxCompressionRatio       = 1024;
	};

	struct Result {
		bool    success = false;
		QString packageId;        // resolved from manifest.json's "id" field
		QString finalPackageDir;  // <packagesDir>/<packageId>, valid only if success
		QString errorMessage;     // human-readable reason, valid only if !success
	};

	// Result of extractToStaging(): the archive has been validated and fully
	// extracted into a private staging directory, but <packagesDir>/<id> has
	// not been touched. Caller must eventually either commit() stagingDir
	// into place or remove it (a failed/abandoned install must not leak
	// staging directories).
	struct StageResult {
		bool    success = false;
		QString packageId;     // from manifest.json's "id" field
		QString version;       // from manifest.json's optional "version" field; "" if absent
		QString stagingDir;    // valid only if success
		QString errorMessage;  // valid only if !success
	};

	struct CommitResult {
		bool    success = false;
		QString finalPackageDir;
		QString errorMessage;
	};

	// Two overloads rather than a `Limits limits = Limits()` default argument:
	// Clang (unlike MSVC) rejects a nested struct's default member
	// initializers used to default-construct it inside a default argument of
	// its own enclosing class -- "needed within definition of enclosing class
	// 'ZipInstaller'". The default-constructed Limits() lives in the .cpp,
	// past the class body, where it's unambiguously fine.
	explicit ZipInstaller(QString packagesDir);
	ZipInstaller(QString packagesDir, Limits limits);

	// Validates and extracts zipPath into a staging directory, then atomically
	// renames it into <packagesDir>/<id> once every entry has passed and
	// manifest.json (required, must contain a string "id" field matching
	// [A-Za-z0-9_-]+) has been read from the extracted root. Fails outright
	// -- staging is discarded -- if <packagesDir>/<id> already exists; use
	// extractToStaging()/commit() for a reinstall-aware caller.
	Result install(const QString &zipPath) const;

	// Validates and extracts zipPath into a fresh staging directory under
	// <packagesDir>/.staging/<uuid>/ without touching <packagesDir>/<id>.
	StageResult extractToStaging(const QString &zipPath) const;

	// Atomically swaps stagingDir into <packagesDir>/<packageId>, replacing
	// whatever was already there if anything (overwrite-by-id). Purely a
	// filesystem operation.
	CommitResult commit(const QString &packageId, const QString &stagingDir) const;

private:
	QString m_packagesDir;
	Limits  m_limits;
};
