#pragma once
#include <QtCore/qstring.h>
#include <QtCore/qvariant.h>
#include <QtCore/qstringlist.h>

/**
 * JsonBuilder - Simple, safe JSON string builder
 *
 * Provides a cleaner, more maintainable way to build JSON strings
 * than manual concatenation. Handles escaping automatically.
 *
 * Example:
 *   JsonBuilder json;
 *   json.startObject();
 *   json.addMember("success", true);
 *   json.addMember("result", 42);
 *   json.addMember("message", "Hello");
 *   json.finishObject();
 *   QString output = json.toString();
 */
class JsonBuilder {
public:
    JsonBuilder();

    void startObject();
    void startArray();
    void finishObject();
    void finishArray();

    // Add object members (key-value pairs)
    void addMember(const QString& name, bool value);
    void addMember(const QString& name, int value);
    void addMember(const QString& name, qint64 value);
    void addMember(const QString& name, double value);
    void addMember(const QString& name, const QString& value);
    void addMemberNull(const QString& name);
    void addMember(const QString& name, const QVariant& value);

    // Add array items
    void addItem(bool value);
    void addItem(int value);
    void addItem(double value);
    void addItem(const QString& value);
    void addItemNull();
    void addItem(const QVariant& value);

    // Get final JSON string
    QString toString() const;

private:
    void addSeparator();
    QString escapeString(const QString& str) const;
    QString variantToJson(const QVariant& v) const;

    QString m_json;
    bool m_needsSeparator;
};
