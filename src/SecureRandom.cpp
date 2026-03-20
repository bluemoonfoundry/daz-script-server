#include "SecureRandom.h"
#include <QtCore/qdebug.h>

#ifdef _WIN32
    // Windows: Use CryptoAPI (available since Windows 2000)
    #include <windows.h>
    #include <wincrypt.h>
    // Link with advapi32.lib (done in CMakeLists.txt)
#else
    // Unix/macOS: Use /dev/urandom (kernel CSPRNG)
    #include <fstream>
#endif

QByteArray SecureRandom::generateBytes(int count)
{
    if (count <= 0) {
        qWarning("SecureRandom::generateBytes: Invalid count %d", count);
        return QByteArray();
    }

    QByteArray randomBytes(count, 0);

#ifdef _WIN32
    // ─── Windows: CryptoAPI ───────────────────────────────────────────────────
    HCRYPTPROV hProvider = 0;

    // Acquire cryptographic context
    // PROV_RSA_FULL: RSA provider with full key exchange and signature capabilities
    // CRYPT_VERIFYCONTEXT: No private key access needed (for RNG only)
    // CRYPT_SILENT: No user interface prompts
    if (!CryptAcquireContext(&hProvider, NULL, NULL, PROV_RSA_FULL,
                             CRYPT_VERIFYCONTEXT | CRYPT_SILENT)) {
        DWORD err = GetLastError();
        qWarning("SecureRandom: CryptAcquireContext failed with error 0x%lx", err);
        return QByteArray();
    }

    // Generate random bytes using Windows crypto API
    BOOL result = CryptGenRandom(hProvider, (DWORD)count, (BYTE*)randomBytes.data());
    DWORD err = result ? 0 : GetLastError();

    // Always release the context
    CryptReleaseContext(hProvider, 0);

    if (!result) {
        qWarning("SecureRandom: CryptGenRandom failed with error 0x%lx", err);
        return QByteArray();
    }

#else
    // ─── Unix/macOS: /dev/urandom ─────────────────────────────────────────────
    // /dev/urandom is the kernel's cryptographically secure PRNG
    // It never blocks (unlike /dev/random) and is suitable for all cryptographic uses
    std::ifstream urandom("/dev/urandom", std::ios::binary);

    if (!urandom.is_open()) {
        qWarning("SecureRandom: Cannot open /dev/urandom");
        return QByteArray();
    }

    urandom.read(randomBytes.data(), count);

    if (!urandom.good()) {
        qWarning("SecureRandom: Failed to read %d bytes from /dev/urandom", count);
        urandom.close();
        return QByteArray();
    }

    urandom.close();
#endif

    return randomBytes;
}

QString SecureRandom::generateHexToken(int byteCount)
{
    QByteArray randomBytes = generateBytes(byteCount);

    if (randomBytes.isEmpty()) {
        qWarning("SecureRandom::generateHexToken: Failed to generate random bytes");
        return QString();
    }

    // Convert to hexadecimal string (2 hex chars per byte)
    return QString(randomBytes.toHex());
}
