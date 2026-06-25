#pragma once

//////////////////////////////////////////////
//
// DazScriptServer Plugin Macros
//
// Adapted from DazBridgeUtils/include/dzbridge.h
//
//////////////////////////////////////////////

#if defined(__APPLE__)
#define CPP_PLUGIN_DEFINITION DZ_PLUGIN_DEFINITION
#elif DAZ_SDK_MAJOR_VERSION >= 6
// SDK6's own DZ_PLUGIN_DEFINITION (Windows) exports getSDKVersion/
// getPluginDefinition without extern "C", so the linker emits C++-mangled
// names (e.g. "?getSDKVersion@@YA?AVDzVersion@@XZ") instead of the plain
// names DAZ Studio's plugin loader does GetProcAddress() on by string —
// real SDK6 samples work around this with a .def file; we add extern "C"
// here instead. Otherwise this mirrors DZ_PLUGIN_DEFINITION exactly,
// including the getPluginInternal()/getFinalPluginDefinition() indirection
// SDK6 needs for the new required finishSetup() step.
#define CPP_PLUGIN_DEFINITION( pluginName ) \
DzPlugin* getPluginInternal() \
{ \
	static DzPlugin s_pluginDef( pluginName ); \
	return &s_pluginDef; \
} \
BOOL WINAPI DllMain( HINSTANCE hinstDLL, ULONG fdwReason, LPVOID lpvReserved )	\
{	\
	switch( fdwReason ) {		\
	case DLL_PROCESS_ATTACH:	\
		break;					\
	case DLL_THREAD_ATTACH:		\
		break;					\
	case DLL_THREAD_DETACH:		\
		break;					\
	case DLL_PROCESS_DETACH:	\
		break;					\
	}							\
	return TRUE;				\
} \
 \
extern "C" __declspec(dllexport) DzVersion getSDKVersion() { return DZ_SDK_VERSION; } \
extern "C" __declspec(dllexport) DzPlugin *getPluginDefinition() { return getFinalPluginDefinition(); }
#else
#define CPP_PLUGIN_DEFINITION( pluginName ) \
BOOL WINAPI DllMain( HINSTANCE hinstDLL, ULONG fdwReason, LPVOID lpvReserved )	\
{	\
	switch( fdwReason ) {		\
	case DLL_PROCESS_ATTACH:	\
		break;					\
	case DLL_THREAD_ATTACH:		\
		break;					\
	case DLL_THREAD_DETACH:		\
		break;					\
	case DLL_PROCESS_DETACH:	\
		break;					\
	}							\
	return TRUE;				\
} \
 \
static DzPlugin s_pluginDef( pluginName ); \
extern "C" __declspec(dllexport) DzVersion getSDKVersion() { return DZ_SDK_VERSION; } \
extern "C" __declspec(dllexport) DzPlugin *getPluginDefinition() { return &s_pluginDef; }
#endif

//////////////////////////////////////////////
//
// Fixed DZ_PLUGIN_CUSTOM_CLASS macro
//
// The original DazSDK macros are missing the proper factory functions to handle arguments
// for custom classes. The following alternative macros fix this.
//
//////////////////////////////////////////////

#include <qwidget.h>
#include <qvariant.h>

static QWidget* getParentFromArgs(const QVariantList& args)
{
	if (args.count() < 1)
		return nullptr;

	QWidget* parent = nullptr;
	QVariant qvar = args[0];
	QObject* obj = qvar.value<QObject*>();
	if (obj)
		parent = qobject_cast<QWidget*>(obj);

	return parent;
}

#define NEW_PLUGIN_CUSTOM_CLASS_GUID( typeName, guid ) \
DZ_PLUGIN_CUSTOM_CLASS_GUID( typeName, guid ) \
 \
QObject* typeName ## Factory::createInstance(const QVariantList& args) const \
{ \
	QWidget* parent = getParentFromArgs(args); \
	return qobject_cast<QObject*>(new typeName(parent)); \
} \
QObject* typeName ## Factory::createInstance() const \
{ \
	return qobject_cast<QObject*>(new typeName(nullptr)); \
}
