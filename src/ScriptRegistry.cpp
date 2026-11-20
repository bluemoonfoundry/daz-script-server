// Split out of DzScriptServerPane.cpp (x7ul.32); see ScriptRegistry.h.
#include "ScriptRegistry.h"
#include "JsonStd.h"
#include <vector>

bool ScriptRegistry::registerScript(const QString& name, const QString& description,
                                    const QString& script, QDateTime* outRegisteredAt)
{
	Entry entry;
	entry.description  = description;
	entry.script       = script;
	entry.registeredAt = QDateTime::currentDateTime();
	if (outRegisteredAt) *outRegisteredAt = entry.registeredAt;

	QByteArray key = name.toUtf8();
	QMutexLocker lock(&m_mutex);
	const bool isUpdate = m_scripts.contains(key);
	m_scripts.insert(key, entry);
	return isUpdate;
}

std::string ScriptRegistry::listJson() const
{
	struct Item { std::string id, description; long long registeredAtMs; };
	std::vector<Item> entries;
	{
		QMutexLocker lock(&m_mutex);
		entries.reserve(m_scripts.size());
		for (QMap<QByteArray, Entry>::const_iterator it = m_scripts.begin();
		     it != m_scripts.end(); ++it) {
			entries.push_back({
			    std::string(it.key().constData(), it.key().size()),
			    JsonStd::qstrToStd(it.value().description),
			    (long long)it.value().registeredAt.toMSecsSinceEpoch()
			});
		}
	}

	std::string items;
	for (size_t i = 0; i < entries.size(); ++i) {
		if (i > 0) items += ",";
		items += "{\"name\":\"" + JsonStd::escape(entries[i].id) + "\"";
		items += ",\"description\":\"" + JsonStd::escape(entries[i].description) + "\"";
		items += ",\"registered_at\":\"" + JsonStd::msecToIso(entries[i].registeredAtMs) + "\"}";
	}
	std::string s = "{\"scripts\":[" + items + "]";
	s += ",\"count\":" + std::to_string(entries.size()) + "}";
	return s;
}

bool ScriptRegistry::remove(const std::string& id)
{
	QByteArray key(id.c_str(), (int)id.size());
	QMutexLocker lock(&m_mutex);
	return m_scripts.remove(key) > 0;
}

bool ScriptRegistry::lookup(const std::string& id, std::string& outScript) const
{
	QByteArray key(id.c_str(), (int)id.size());
	QMutexLocker lock(&m_mutex);
	if (!m_scripts.contains(key))
		return false;
	outScript = JsonStd::qstrToStd(m_scripts.value(key).script);
	return true;
}
