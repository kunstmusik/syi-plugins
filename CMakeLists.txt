cmake_minimum_required(VERSION 3.18)
project(syi-plugins VERSION 0.1.0 LANGUAGES C)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

find_path(CSOUND_INCLUDE_DIR csdl.h
  PATHS /Library/Frameworks/CsoundLib64.framework/Headers
        "$ENV{HOME}/Library/Frameworks/CsoundLib64.framework/Headers"
  PATH_SUFFIXES csound)
if(NOT CSOUND_INCLUDE_DIR)
  message(FATAL_ERROR "Set CSOUND_INCLUDE_DIR to the matching Csound 7 SDK headers")
endif()

# Follow the SDK's API version and precision rather than assuming double samples.
foreach(part VERSION SUBVER)
  file(STRINGS "${CSOUND_INCLUDE_DIR}/version.h" version_define
    REGEX "^#define[ \t]+CS_${part}[ \t]+")
  string(REGEX MATCH "[0-9]+" CSOUND_${part} "${version_define}")
endforeach()
if(NOT CSOUND_VERSION STREQUAL "7" OR CSOUND_SUBVER STREQUAL "")
  message(FATAL_ERROR "Csound 7 SDK headers with version.h are required")
endif()
set(CSOUND_API_VERSION "${CSOUND_VERSION}.${CSOUND_SUBVER}")

include(CheckTypeSize)
set(CMAKE_REQUIRED_INCLUDES "${CSOUND_INCLUDE_DIR}")
set(CMAKE_EXTRA_INCLUDE_FILES csdl.h)
check_type_size(cs_float CSOUND_SAMPLE_SIZE LANGUAGE C)
unset(CMAKE_REQUIRED_INCLUDES)
unset(CMAKE_EXTRA_INCLUDE_FILES)
if(CSOUND_SAMPLE_SIZE EQUAL 8)
  set(plugin_directory plugins64)
elseif(CSOUND_SAMPLE_SIZE EQUAL 4)
  set(plugin_directory plugins)
else()
  message(FATAL_ERROR "Could not determine the Csound SDK sample precision")
endif()

# Match Csound's DEFAULT_USER_PLUGINDIR in its top-level CMakeLists.txt.
if(NOT DEFINED PLUGIN_INSTALL_DIR)
  if(WIN32)
    set(user_prefix "$ENV{LOCALAPPDATA}")
    # The current Csound Windows float build uses singular 'plugin'.
    if(CSOUND_SAMPLE_SIZE EQUAL 4)
      set(plugin_directory plugin)
    endif()
    set(user_plugin_path "csound/${CSOUND_API_VERSION}/${plugin_directory}")
  elseif(APPLE)
    set(user_prefix "$ENV{HOME}")
    set(user_plugin_path "Library/csound/${CSOUND_API_VERSION}/${plugin_directory}")
  elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(user_prefix "$ENV{HOME}")
    set(user_plugin_path ".local/lib/csound/${CSOUND_API_VERSION}/${plugin_directory}")
  else()
    message(FATAL_ERROR "Set PLUGIN_INSTALL_DIR for this platform")
  endif()
  if(user_prefix STREQUAL "")
    message(FATAL_ERROR "User home directory is unavailable; set PLUGIN_INSTALL_DIR")
  endif()
  file(TO_CMAKE_PATH "${user_prefix}/${user_plugin_path}" user_plugin_directory)
  set(PLUGIN_INSTALL_DIR "${user_plugin_directory}" CACHE PATH
    "Csound user opcode plugin install directory")
endif()
message(STATUS "Csound ${CSOUND_API_VERSION}, ${CSOUND_SAMPLE_SIZE}-byte samples")
message(STATUS "Opcode libraries will install to: ${PLUGIN_INSTALL_DIR}")

include(CTest)
add_subdirectory(juno60vcf)
