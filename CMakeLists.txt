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

include(CTest)
add_subdirectory(juno60vcf)
