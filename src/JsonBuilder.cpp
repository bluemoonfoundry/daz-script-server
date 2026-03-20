#include "JsonBuilder.h"
#include <QtCore/qvariant.h>

JsonBuilder::JsonBuilder()
    : m_needsSeparator(false)
{
}

void JsonBuilder::startObject()
{
    m_json += "{";
    m_needsSeparator = false;
}

void JsonBuilder::startArray()
{
    m_json += "[";
    m_needsSeparator = false;
}

void JsonBuilder::finishObject()
{
    m_json += "}";
    m_needsSeparator = true;
}

void JsonBuilder::finishArray()
{
    m_json += "]";
    m_needsSeparator = true;
}

void JsonBuilder::addSeparator()
{
    if (m_needsSeparator) {
        m_json += ",";
    }
    m_needsSeparator = true;
}

QString JsonBuilder::escapeString(const QString& str) const
{
    QString escaped = str;
    escaped.replace('\\', "\\\\");
    escaped.replace('"',  "\\\"");
    escaped.replace('\n', "\\n");
    escaped.replace('\r', "\\r");
    escaped.replace('\t', "\\t");
    escaped.replace('\b', "\\b");
    escaped.replace('\f', "\\f");
    return escaped;
}

// ─── Add object members ───────────────────────────────────────────────────────

void JsonBuilder::addMember(const QString& name, bool value)
{
    addSeparator();
    m_json += "\"" + escapeString(name) + "\":";
    m_json += value ? "true" : "false";
}

void JsonBuilder::addMember(const QString& name, int value)
{
    addSeparator();
    m_json += "\"" + escapeString(name) + "\":";
    m_json += QString::number(value);
}

void JsonBuilder::addMember(const QString& name, qint64 value)
{
    addSeparator();
    m_json += "\"" + escapeString(name) + "\":";
    m_json += QString::number(value);
}

void JsonBuilder::addMember(const QString& name, double value)
{
    addSeparator();
    m_json += "\"" + escapeString(name) + "\":";
    m_json += QString::number(value, 'g', 15);
}

void JsonBuilder::addMember(const QString& name, const QString& value)
{
    addSeparator();
    m_json += "\"" + escapeString(name) + "\":";
    m_json += "\"" + escapeString(value) + "\"";
}

void JsonBuilder::addMemberNull(const QString& name)
{
    addSeparator();
    m_json += "\"" + escapeString(name) + "\":null";
}

void JsonBuilder::addMember(const QString& name, const QVariant& value)
{
    addSeparator();
    m_json += "\"" + escapeString(name) + "\":";
    m_json += variantToJson(value);
}

// ─── Add array items ──────────────────────────────────────────────────────────

void JsonBuilder::addItem(bool value)
{
    addSeparator();
    m_json += value ? "true" : "false";
}

void JsonBuilder::addItem(int value)
{
    addSeparator();
    m_json += QString::number(value);
}

void JsonBuilder::addItem(double value)
{
    addSeparator();
    m_json += QString::number(value, 'g', 15);
}

void JsonBuilder::addItem(const QString& value)
{
    addSeparator();
    m_json += "\"" + escapeString(value) + "\"";
}

void JsonBuilder::addItemNull()
{
    addSeparator();
    m_json += "null";
}

void JsonBuilder::addItem(const QVariant& value)
{
    addSeparator();
    m_json += variantToJson(value);
}

// ─── Variant to JSON conversion ───────────────────────────────────────────────

QString JsonBuilder::variantToJson(const QVariant& v) const
{
    if (!v.isValid() || v.isNull())
        return "null";

    switch (v.type()) {
    case QVariant::Bool:
        return v.toBool() ? "true" : "false";
    case QVariant::Int:
    case QVariant::LongLong:
    case QVariant::UInt:
    case QVariant::ULongLong:
        return QString::number(v.toLongLong());
    case QVariant::Double:
        return QString::number(v.toDouble(), 'g', 15);
    case QVariant::String: {
        return "\"" + escapeString(v.toString()) + "\"";
    }
    case QVariant::List:
    case QVariant::StringList: {
        QVariantList list = v.toList();
        QString json = "[";
        for (int i = 0; i < list.size(); ++i) {
            if (i > 0) json += ",";
            json += variantToJson(list.at(i));
        }
        json += "]";
        return json;
    }
    case QVariant::Map: {
        QVariantMap map = v.toMap();
        QString json = "{";
        bool first = true;
        for (QVariantMap::const_iterator it = map.begin(); it != map.end(); ++it) {
            if (!first) json += ",";
            first = false;
            json += "\"" + escapeString(it.key()) + "\":";
            json += variantToJson(it.value());
        }
        json += "}";
        return json;
    }
    default:
        return "\"" + escapeString(v.toString()) + "\"";
    }
}

QString JsonBuilder::toString() const
{
    return m_json;
}
