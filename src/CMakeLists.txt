set(CMAKE_AUTOMOC ON)
set(CMAKE_INCLUDE_CURRENT_DIR ON)

include_directories(${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_SOURCE_DIR}/../include)

add_library(DazScriptServer SHARED
	pluginmain.cpp
	DzScriptServerPane.cpp
	httplib.h
	../include/DzScriptServerPane.h
	../include/common_version.h
	../include/dzscriptserver.h
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
	target_link_libraries(DazScriptServer PRIVATE ws2_32)
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
endif()
