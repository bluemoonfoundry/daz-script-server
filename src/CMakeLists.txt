set(CMAKE_AUTOMOC ON)
set(CMAKE_INCLUDE_CURRENT_DIR ON)

include_directories(${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_SOURCE_DIR}/../include)

add_library(DazScriptServer SHARED
	pluginmain.cpp
	DzScriptServerPane.cpp
	RenderProgressBroker.cpp
	AsyncRequestManager.cpp
	AuthenticationService.cpp
	RateLimiterService.cpp
	IPWhitelistService.cpp
	MetricsCollector.cpp
	SecureRandom.cpp
	JsonBuilder.cpp
	RequestHandlers.cpp
	ErrorResponse.cpp
	RequestValidator.cpp
	SettingsService.cpp
	SceneEventBroker.cpp
	# Package Runner (daz-script-server-5sw): open a .dzpkg the same way a
	# .dsa is opened today, run it as a one-shot subprocess against a
	# lazily-created per-package venv. Ported from daz-python-bridge's
	# ZipInstaller/UvBootstrapper/PluginDependencyInstaller.
	ZipInstaller.cpp
	miniz.c
	PackagePaths.cpp
	PythonToolchainBootstrapper.cpp
	PackageDependencyInstaller.cpp
	httplib.h
	../include/DzScriptServerPane.h
	../include/AsyncRequestManager.h
	../include/AuthenticationService.h
	../include/RateLimiterService.h
	../include/IPWhitelistService.h
	../include/MetricsCollector.h
	../include/SecureRandom.h
	../include/JsonBuilder.h
	../include/JsonStd.h
	../include/RequestHandler.h
	../include/ErrorResponse.h
	../include/RequestValidator.h
	../include/common_version.h
	../include/dzscriptserver.h
	../include/SettingsService.h
	../include/ServerSettings.h
	../include/SceneEventBroker.h
	../include/RenderProgressBroker.h
	../include/ZipInstaller.h
	../include/PortableFs.h
	../include/PackagePaths.h
	../include/PythonToolchainBootstrapper.h
	../include/PackageDependencyInstaller.h
	miniz.h
)

target_include_directories(DazScriptServer
	PRIVATE
	${CMAKE_CURRENT_SOURCE_DIR}
	${CMAKE_CURRENT_SOURCE_DIR}/../include
)

target_link_libraries(DazScriptServer
	PRIVATE
	dzcore
	${DZSDK_QT_CORE_TARGET}
	${DZSDK_QT_GUI_TARGET}
	${DZSDK_QT_NETWORK_TARGET}
	${DZSDK_QT_SCRIPT_TARGET}
)

if(WIN32)
	target_link_libraries(DazScriptServer PRIVATE ws2_32 advapi32)
	# Emit a PDB for every build config so VS Code / WinDbg can resolve symbols.
	target_compile_options(DazScriptServer PRIVATE /Zi)
	target_link_options(DazScriptServer PRIVATE /DEBUG /OPT:REF /OPT:ICF)
	if(DAZ_SDK_VERSION STREQUAL "6")
		target_link_libraries(DazScriptServer PRIVATE dzsdkmemory)
	endif()
endif()

target_compile_definitions(DazScriptServer PRIVATE
	CPPHTTPLIB_NO_COMPRESS
	DAZ_SDK_MAJOR_VERSION=${DAZ_SDK_VERSION}
)

# SDK6's plugin scanner only recognizes DLLs named with the "dsp_" prefix
# (DZ_PLUGIN_PREFIX in the SDK6 CMakeLists.txt / every SDK6 sample's output
# name) — without it, DAZ Studio 6 silently skips the DLL at startup. SDK4
# has no such requirement, so keep its filename unprefixed/unchanged.
if(DAZ_SDK_VERSION STREQUAL "6")
	set(DAZSCRIPTSERVER_OUTPUT_NAME "dsp_DazScriptServer")
else()
	set(DAZSCRIPTSERVER_OUTPUT_NAME "DazScriptServer")
endif()

set_target_properties(DazScriptServer PROPERTIES
	OUTPUT_NAME "${DAZSCRIPTSERVER_OUTPUT_NAME}"
	PREFIX ""
	FOLDER ""
	PROJECT_LABEL "DazScriptServer"
)

if(INSTALL_TO_DAZ AND DAZ_STUDIO_EXE_DIR)
	install(TARGETS DazScriptServer
		RUNTIME DESTINATION "${DAZ_STUDIO_EXE_DIR}/plugins"
		LIBRARY DESTINATION "${DAZ_STUDIO_EXE_DIR}/plugins"
	)
	if(WIN32)
		install(FILES
			$<TARGET_PDB_FILE:DazScriptServer>
			DESTINATION "${DAZ_STUDIO_EXE_DIR}/plugins"
			OPTIONAL
		)
	endif()
endif()
