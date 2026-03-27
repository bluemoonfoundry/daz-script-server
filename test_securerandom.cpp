/**
 * Simple test for SecureRandom class
 * Compile: g++ -o test_securerandom test_securerandom.cpp src/SecureRandom.cpp -I./include -I/path/to/qt4/include
 */
#include <iostream>
#include <cstdlib>
#include "SecureRandom.h"

int main() {
    std::cout << "Testing SecureRandom class...\n\n";

    // Test 1: Generate random bytes
    std::cout << "Test 1: Generate 16 random bytes\n";
    QByteArray bytes = SecureRandom::generateBytes(16);
    if (bytes.isEmpty()) {
        std::cerr << "FAIL: generateBytes returned empty array\n";
        return 1;
    }
    std::cout << "SUCCESS: Generated " << bytes.size() << " bytes\n";
    std::cout << "Hex: " << bytes.toHex().constData() << "\n\n";

    // Test 2: Generate hex token (default 16 bytes = 32 hex chars)
    std::cout << "Test 2: Generate default hex token (128 bits)\n";
    QString token1 = SecureRandom::generateHexToken();
    if (token1.isEmpty()) {
        std::cerr << "FAIL: generateHexToken returned empty string\n";
        return 1;
    }
    if (token1.length() != 32) {
        std::cerr << "FAIL: Expected 32 hex chars, got " << token1.length() << "\n";
        return 1;
    }
    std::cout << "SUCCESS: Generated token with " << token1.length() << " hex chars\n";
    std::cout << "Token: " << token1.toStdString() << "\n\n";

    // Test 3: Generate multiple tokens and verify they're different
    std::cout << "Test 3: Generate 5 tokens and verify uniqueness\n";
    QString tokens[5];
    for (int i = 0; i < 5; i++) {
        tokens[i] = SecureRandom::generateHexToken();
        if (tokens[i].isEmpty()) {
            std::cerr << "FAIL: Token " << i << " is empty\n";
            return 1;
        }
        std::cout << "Token " << i << ": " << tokens[i].toStdString() << "\n";
    }

    // Check for duplicates
    bool allUnique = true;
    for (int i = 0; i < 5; i++) {
        for (int j = i + 1; j < 5; j++) {
            if (tokens[i] == tokens[j]) {
                std::cerr << "FAIL: Tokens " << i << " and " << j << " are identical!\n";
                allUnique = false;
            }
        }
    }

    if (allUnique) {
        std::cout << "SUCCESS: All tokens are unique\n\n";
    } else {
        return 1;
    }

    // Test 4: Test different sizes
    std::cout << "Test 4: Generate tokens of different sizes\n";
    QString token8 = SecureRandom::generateHexToken(8);   // 64 bits
    QString token32 = SecureRandom::generateHexToken(32); // 256 bits

    if (token8.length() != 16 || token32.length() != 64) {
        std::cerr << "FAIL: Wrong token lengths (got "
                  << token8.length() << " and " << token32.length() << ")\n";
        return 1;
    }
    std::cout << "SUCCESS: 64-bit token:  " << token8.toStdString() << "\n";
    std::cout << "SUCCESS: 256-bit token: " << token32.toStdString() << "\n\n";

    std::cout << "All tests passed!\n";
    return 0;
}
