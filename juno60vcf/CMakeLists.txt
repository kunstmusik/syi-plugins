find_package(PkgConfig REQUIRED)
pkg_check_modules(SAMPLERATE REQUIRED IMPORTED_TARGET samplerate)

add_library(juno60vcf MODULE src/juno60vcf.c)
target_compile_features(juno60vcf PRIVATE c_std_99)
target_include_directories(juno60vcf SYSTEM PRIVATE "${CSOUND_INCLUDE_DIR}")
target_link_libraries(juno60vcf PRIVATE PkgConfig::SAMPLERATE)
if(NOT MSVC)
  target_compile_options(juno60vcf PRIVATE -Wall -Wextra -Wpedantic)
  target_link_libraries(juno60vcf PRIVATE m)
endif()
set_target_properties(juno60vcf PROPERTIES PREFIX "")
if(APPLE)
  set_target_properties(juno60vcf PROPERTIES SUFFIX ".dylib")
endif()

install(TARGETS juno60vcf
  LIBRARY DESTINATION "${PLUGIN_INSTALL_DIR}"
  RUNTIME DESTINATION "${PLUGIN_INSTALL_DIR}")

if(BUILD_TESTING)
  find_package(Python3 COMPONENTS Interpreter REQUIRED)
  find_program(CSOUND_EXECUTABLE csound REQUIRED)
  add_test(NAME juno60vcf
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/check_juno60vcf.py"
            "$<TARGET_FILE:juno60vcf>" "${CSOUND_EXECUTABLE}")
  add_test(NAME juno60vcf_research
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/check_research.py"
            "$<TARGET_FILE:juno60vcf>")
endif()
