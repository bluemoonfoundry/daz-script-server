cmake_minimum_required(VERSION 3.5)

set(CMAKE_CONFIGURATION_TYPES ${CMAKE_CONFIGURATION_TYPES} "MinSizeRel;RelWithDebInfo;Debug;Release")
set(CMAKE_BUILD_TYPE "Release" CACHE STRING "" FORCE)

if(APPLE)
	set(CMAKE_OSX_ARCHITECTURES "x86_64" CACHE STRING "" FORCE)
	if(NOT CMAKE_OSX_ARCHITECTURES)
		message(FATAL_ERROR "Mac needs CMAKE_OSX_ARCHITECTURES, set to i386 or x86_64")
		return()
	endif()
endif(APPLE)

project("DazScriptServer")

set(DAZ_STUDIO_EXE_DIR "" CACHE PATH "Path to DAZ Studio executable folder (for plugin installation)")

set_property(GLOBAL PROPERTY USE_FOLDERS ON)

# ─── Platform detection ──────────────────────────────────────────────────────

if(WIN32)
	set(DZ_LIB_SUFFIX ".lib")
	set(DZ_BIN_SUFFIX ".dll")
	set(DZ_LIB_PREFIX "")
	set(UTIL_EXT ".exe")
	if(CMAKE_SIZEOF_VOID_P EQUAL 4)
		set(DZ_PLATFORM x86)
		set(DZ_MIXED_PLATFORM Win32)
		set(DZ_OS_PLATFORM Win32)
	elseif(CMAKE_SIZEOF_VOID_P EQUAL 8)
		set(DZ_PLATFORM x64)
		set(DZ_MIXED_PLATFORM x64)
		set(DZ_OS_PLATFORM Win64)
	else()
		message(FATAL_ERROR "Unknown architecture")
	endif()
elseif(APPLE)
	set(DZ_LIB_SUFFIX ".dylib")
	set(DZ_BIN_SUFFIX ".dylib")
	set(DZ_LIB_PREFIX "lib")
	set(UTIL_EXT "")
	if(CMAKE_SIZEOF_VOID_P EQUAL 4)
		set(DZ_PLATFORM x86)
		set(DZ_MIXED_PLATFORM Mac32)
		set(DZ_OS_PLATFORM Mac32)
	elseif(CMAKE_SIZEOF_VOID_P EQUAL 8)
		set(DZ_PLATFORM x64)
		set(DZ_MIXED_PLATFORM Mac64)
		set(DZ_OS_PLATFORM Mac64)
	else()
		message(FATAL_ERROR "Unknown architecture")
	endif()
	set(CMAKE_MACOSX_RPATH TRUE)
	set(CMAKE_BUILD_WITH_INSTALL_RPATH TRUE)
	set(CMAKE_CXX_FLAGS "-std=c++11 -stdlib=libc++ ${CMAKE_CXX_FLAGS}")
else()
	message(FATAL_ERROR "Unsupported platform")
endif(WIN32)

# ─── DAZ SDK ─────────────────────────────────────────────────────────────────

set(DAZ_SDK_CORE_RELATIVE_PATH "lib/${DZ_MIXED_PLATFORM}/${DZ_LIB_PREFIX}dzcore${DZ_LIB_SUFFIX}")

set(DAZ_SDK_DIR_DEFAULT "")
if(NOT DAZ_SDK_DIR)
	if(EXISTS "${CMAKE_CURRENT_LIST_DIR}/DAZStudio4.5+ SDK/${DAZ_SDK_CORE_RELATIVE_PATH}")
		set(DAZ_SDK_DIR_DEFAULT "${CMAKE_CURRENT_LIST_DIR}/DAZStudio4.5+ SDK")
	endif()
endif()

set(DAZ_SDK_DIR ${DAZ_SDK_DIR_DEFAULT} CACHE PATH "Path to root of the DAZ Studio SDK")

if(NOT DAZ_SDK_DIR)
	message(FATAL_ERROR "Missing path to DAZ Studio SDK (set DAZ_SDK_DIR)")
	return()
endif()

# We only have release libraries for dzcore/Qt — use /MD and undef _DEBUG even in Debug builds.
if(WIN32)
	add_compile_options("/MD" "/U_DEBUG")
endif()

# dzcore import target
set(DZ_SDK_INCLUDE "${DAZ_SDK_DIR}/include" CACHE FILEPATH "Path to DAZ SDK includes")
set(DAZ_SDK_LIB    "${DAZ_SDK_DIR}/${DAZ_SDK_CORE_RELATIVE_PATH}" CACHE FILEPATH "Path to dzcore")
if(NOT EXISTS ${DAZ_SDK_LIB})
	message(FATAL_ERROR "dzcore library not found — check DAZ_SDK_DIR: ${DAZ_SDK_DIR}")
	return()
endif()

add_library(dzcore SHARED IMPORTED)
if(WIN32)
	set_property(TARGET dzcore APPEND PROPERTY IMPORTED_IMPLIB ${DAZ_SDK_LIB})
else()
	set_property(TARGET dzcore APPEND PROPERTY IMPORTED_LOCATION ${DAZ_SDK_LIB})
endif()
set_property(TARGET dzcore APPEND PROPERTY INTERFACE_INCLUDE_DIRECTORIES "${DZ_SDK_INCLUDE}")

# dpc import target (Daz pre-compiler)
set(DAZ_SDK_DPC_EXE "${DAZ_SDK_DIR}/bin/${DZ_MIXED_PLATFORM}/dpc${UTIL_EXT}" CACHE FILEPATH "Path to SDK dpc")
if(NOT EXISTS ${DAZ_SDK_DPC_EXE})
	message(FATAL_ERROR "dpc executable not found — check DAZ_SDK_DIR: ${DAZ_SDK_DIR}")
	return()
endif()
add_executable(dpc IMPORTED)
set_property(TARGET dpc APPEND PROPERTY IMPORTED_LOCATION ${DAZ_SDK_DPC_EXE})

# ─── Qt 4.8 (from DAZ SDK) ───────────────────────────────────────────────────

if(WIN32)
	set(DAZ_SDK_QTCORE_LIBRARY "${DAZ_SDK_DIR}/lib/${DZ_MIXED_PLATFORM}/QtCore4.lib")
elseif(APPLE)
	set(DAZ_SDK_QTCORE_LIBRARY "${DAZ_SDK_DIR}/lib/${DZ_MIXED_PLATFORM}/QtCore.framework")
endif()

set(QT_BINARY_DIR_DEFAULT "${DAZ_SDK_DIR}/bin/${DZ_MIXED_PLATFORM}")
set(QT_IMPORTS_DIR        "${DAZ_SDK_DIR}/lib/${DZ_MIXED_PLATFORM}")
set(QT_QTCORE_LIBRARY_RELEASE ${DAZ_SDK_QTCORE_LIBRARY})
set(QT_QMAKE_EXECUTABLE   "${DAZ_SDK_DIR}/bin/${DZ_MIXED_PLATFORM}/qmake${UTIL_EXT}")
set(QT_BINARY_DIR         "${DAZ_SDK_DIR}/bin/${DZ_MIXED_PLATFORM}")
set(QT_HEADERS_DIR        "${DAZ_SDK_DIR}/include")
set(QT_QTCORE_INCLUDE_DIR "${DAZ_SDK_DIR}/include/QtCore")

# The Qt find module needs this folder; fake it.
file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/DUMMY_MKSPECS/default")
set(QT_MKSPECS_DIR "${CMAKE_CURRENT_BINARY_DIR}/DUMMY_MKSPECS")

find_package(Qt4 4.8.1 REQUIRED QtCore QtGui QtScript QtNetwork)

set(DZSDK_QT_CORE_TARGET    Qt4::QtCore)
set(DZSDK_QT_GUI_TARGET     Qt4::QtGui)
set(DZSDK_QT_SCRIPT_TARGET  Qt4::QtScript)
set(DZSDK_QT_NETWORK_TARGET Qt4::QtNetwork)

list(APPEND CMAKE_AUTOMOC_MOC_OPTIONS -i)

# ─── Output directories ───────────────────────────────────────────────────────

set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)

# ─── Optional: copy plugin directly to Daz Studio plugins folder ──────────────

option(INSTALL_TO_DAZ "Copy DLL to DAZ_STUDIO_EXE_DIR/plugins after build" OFF)
if(INSTALL_TO_DAZ)
	if(NOT DAZ_STUDIO_EXE_DIR)
		message(FATAL_ERROR "INSTALL_TO_DAZ requires DAZ_STUDIO_EXE_DIR to be set")
	endif()
	set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${DAZ_STUDIO_EXE_DIR}/plugins")
	set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${DAZ_STUDIO_EXE_DIR}/plugins")
endif()

# ─── Subdirectories ───────────────────────────────────────────────────────────

add_subdirectory("src")
