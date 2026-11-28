#pragma once

#include <QByteArray>
#include <QString>

// SHA-256 of a file's contents, as a lowercase hex digest.
//
// QCryptographicHash::Sha256 is Qt5+ only; Qt 4.8 (SDK4 build) has just
// MD4/MD5/SHA-1, so the SDK4 build uses the OS crypto API instead (Windows
// CryptoAPI from advapi32 -- already linked for SecureRandom -- or Apple's
// CommonCrypto). Returns an empty QByteArray and sets *error on failure.
namespace FileSha256 {

QByteArray hexDigest(const QString &path, QString *error);

} // namespace FileSha256
