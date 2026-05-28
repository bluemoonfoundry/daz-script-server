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
	httplib.h
	../include/DzScriptServerPane.h
	../include/AsyncRequestManager.h
	../include/AuthenticationService.h
	../include/RateLimiterService.h
	../include/IPWhitelistService.h
	../include/MetricsCollector.h
	../include/SecureRandom.h
	../include/JsonBuilder.h
	../include/RequestHandler.h
	../include/ErrorResponse.h
	../include/RequestValidator.h
	../include/common_version.h
	../include/dzscriptserver.h
	../include/SettingsService.h
	../include/ServerSettings.h
	../include/SceneEventBroker.h
	../include/RenderProgressBroker.h
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
	${DZSDK_QT_SCRIPT_TARGET}
	${DZSDK_QT_NETWORK_TARGET}
)

if(WIN32)
	target_link_libraries(DazScriptServer PRIVATE ws2_32 advapi32)
	# Emit a PDB for every build config so VS Code / WinDbg can resolve symbols.
	target_compile_options(DazScriptServer PRIVATE /Zi)
	target_link_options(DazScriptServer PRIVATE /DEBUG /OPT:REF /OPT:ICF)
endif()

target_compile_definitions(DazScriptServer PRIVATE CPPHTTPLIB_NO_COMPRESS)

set_target_properties(DazScriptServer PROPERTIES
	OUTPUT_NAME "DazScriptServer"
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
