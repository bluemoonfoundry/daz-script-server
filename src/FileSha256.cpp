#include "FileSha256.h"

#include <QFile>

#if DAZ_SDK_MAJOR_VERSION >= 6
#include <QCryptographicHash>
#elif defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <wincrypt.h>
#elif defined(__APPLE__)
#include <CommonCrypto/CommonDigest.h>
#else
#error "FileSha256: no SHA-256 implementation for this Qt/platform combination"
#endif

namespace {

const qint64 kChunkSize = 1 << 16;

bool fail(QString *error, const QString &message) {
	if (error) {
		*error = message;
	}
	return false;
}

} // namespace

namespace FileSha256 {

QByteArray hexDigest(const QString &path, QString *error) {
	QFile file(path);
	if (!file.open(QIODevice::ReadOnly)) {
		fail(error, QString::fromLatin1("could not open %1: %2").arg(path, file.errorString()));
		return QByteArray();
	}

#if DAZ_SDK_MAJOR_VERSION >= 6
	QCryptographicHash hash(QCryptographicHash::Sha256);
	if (!hash.addData(&file)) {
		fail(error, QString::fromLatin1("could not read %1: %2").arg(path, file.errorString()));
		return QByteArray();
	}
	return hash.result().toHex();
#elif defined(_WIN32)
	// PROV_RSA_AES is the CryptoAPI provider type that offers CALG_SHA_256
	// (the default PROV_RSA_FULL does not).
	HCRYPTPROV provider = 0;
	if (!CryptAcquireContextW(&provider, nullptr, nullptr, PROV_RSA_AES, CRYPT_VERIFYCONTEXT)) {
		fail(error, QString::fromLatin1("CryptAcquireContext failed (%1)").arg(GetLastError()));
		return QByteArray();
	}
	HCRYPTHASH hash = 0;
	if (!CryptCreateHash(provider, CALG_SHA_256, 0, 0, &hash)) {
		fail(error, QString::fromLatin1("CryptCreateHash failed (%1)").arg(GetLastError()));
		CryptReleaseContext(provider, 0);
		return QByteArray();
	}

	QByteArray digest;
	bool ok = true;
	while (ok && !file.atEnd()) {
		const QByteArray chunk = file.read(kChunkSize);
		if (chunk.isEmpty() && file.error() != QFile::NoError) {
			ok = fail(error, QString::fromLatin1("could not read %1: %2").arg(path, file.errorString()));
		} else if (!CryptHashData(hash, reinterpret_cast<const BYTE *>(chunk.constData()),
		                          static_cast<DWORD>(chunk.size()), 0)) {
			ok = fail(error, QString::fromLatin1("CryptHashData failed (%1)").arg(GetLastError()));
		}
	}
	if (ok) {
		DWORD size = 32;
		digest.resize(32);
		if (!CryptGetHashParam(hash, HP_HASHVAL, reinterpret_cast<BYTE *>(digest.data()), &size, 0) || size != 32) {
			ok = fail(error, QString::fromLatin1("CryptGetHashParam failed (%1)").arg(GetLastError()));
		}
	}
	CryptDestroyHash(hash);
	CryptReleaseContext(provider, 0);
	return ok ? digest.toHex() : QByteArray();
#else
	CC_SHA256_CTX context;
	CC_SHA256_Init(&context);
	while (!file.atEnd()) {
		const QByteArray chunk = file.read(kChunkSize);
		if (chunk.isEmpty() && file.error() != QFile::NoError) {
			fail(error, QString::fromLatin1("could not read %1: %2").arg(path, file.errorString()));
			return QByteArray();
		}
		CC_SHA256_Update(&context, chunk.constData(), static_cast<CC_LONG>(chunk.size()));
	}
	QByteArray digest(CC_SHA256_DIGEST_LENGTH, '\0');
	CC_SHA256_Final(reinterpret_cast<unsigned char *>(digest.data()), &context);
	return digest.toHex();
#endif
}

} // namespace FileSha256
