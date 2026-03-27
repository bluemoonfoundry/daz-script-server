#pragma once
#include <QtCore/qbytearray.h>
#include <QtCore/qstring.h>

/**
 * SecureRandom - Cryptographically secure random number generator
 *
 * Uses platform-specific cryptographic APIs:
 * - Windows: CryptoAPI (CryptGenRandom)
 * - Unix/macOS: /dev/urandom
 *
 * These are suitable for generating security tokens, keys, and other
 * cryptographic material.
 */
class SecureRandom {
public:
    /**
     * Generate cryptographically secure random bytes.
     *
     * @param count Number of random bytes to generate
     * @return QByteArray containing random bytes, or empty QByteArray on failure
     */
    static QByteArray generateBytes(int count);

    /**
     * Generate a cryptographically secure random token as hexadecimal string.
     *
     * @param byteCount Number of random bytes (default: 16 bytes = 128 bits)
     * @return Hexadecimal string (length = byteCount * 2), or empty QString on failure
     */
    static QString generateHexToken(int byteCount = 16);
};
