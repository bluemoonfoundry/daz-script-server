#include <dzplugin.h>
#include <dzapp.h>
#include <dzaction.h>

#include "common_version.h"
#include "DzScriptServerPane.h"

#include "dzscriptserver.h"

// DzPaneAction companion — this is what registers the pane in Window → Panes.
// No implementation needed; the base class handles everything.
class DzScriptServerPaneAction : public DzPaneAction {
	Q_OBJECT
public:
	DzScriptServerPaneAction() : DzPaneAction("DzScriptServerPane") {}
};

#include "pluginmain.moc"

CPP_PLUGIN_DEFINITION("Daz Script Server")

DZ_PLUGIN_AUTHOR("DazScriptServer Contributors");

DZ_PLUGIN_VERSION(DZSRV_MAJOR, DZSRV_MINOR, DZSRV_REV, DZSRV_BUILD);

DZ_PLUGIN_DESCRIPTION(QString(
	"Embedded HTTP server that executes Daz Script on the main thread and returns "
	"the result as JSON. Source: https://github.com/yhirose/cpp-httplib"
));

DZ_PLUGIN_CLASS_GUID(DzScriptServerPane,       c3d4e5f6-a7b8-9012-cdef-123456789012);
DZ_PLUGIN_CLASS_GUID(DzScriptServerPaneAction, d4e5f6a7-b8c9-0123-defa-234567890123);
