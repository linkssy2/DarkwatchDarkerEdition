cmake_minimum_required(VERSION 3.25)
project(darkwatch_xbe LANGUAGES C CXX)
option(DARKWATCH_RELEASE "Build a quiet runtime for the own-ISO launcher" OFF)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
include("${CMAKE_CURRENT_SOURCE_DIR}/../third_party/XboxXBERecomp/cmake/XbeRecomp.cmake")
set(XBE_HOST_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/src/common/game_info.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/script_timing.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/shader_preparation.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/controls.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/coop.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/coop_view.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/coop_menu.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/coop_stream.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/coop_video.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/menu_cursor.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/native_menu.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/desktop_quit.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/prompts.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/graphics.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/graphics_route.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/graphics_camera.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/graphics_cinematic.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/graphics_view.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/graphics_reticle.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/graphics_hud.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/hd_ui.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/cri_diagnostic.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/cri_lifetime.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/sound_pool.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/horse_diagnostic.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/horse_voice_diagnostic.cpp")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS config/game.toml)
file(STRINGS config/game.toml GAME_PARTITIONS REGEX "^partitions *=")
string(REGEX MATCH "[0-9]+" GAME_PARTITIONS "${GAME_PARTITIONS}")
if(NOT GAME_PARTITIONS)
    message(FATAL_ERROR "game.toml must declare the generated partition count")
endif()
add_xbe_image(darkwatch_xbe default.xbe game.toml ${GAME_PARTITIONS} game)
# Any shader-generation/cache change invalidates the portable preparation stamp.
set(SHADER_PREPARATION_INPUTS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/shader_preparation.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/shader_preparation.h"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/common/shader_preparation_catalogue.h"
    "${CMAKE_CURRENT_SOURCE_DIR}/config/game.toml"
    "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/XboxXBERecomp/runtime/gpu/shaders.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/XboxXBERecomp/runtime/gpu/shaders.h"
    "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/XboxXBERecomp/runtime/gpu/vertex.h"
    "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/XboxXBERecomp/runtime/gpu/state.h"
    "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/XboxXBERecomp/runtime/gpu/d3d12.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/XboxXBERecomp/runtime/gpu/backend.h")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${SHADER_PREPARATION_INPUTS})
set(SHADER_PREPARATION_FINGERPRINT "")
foreach(shader_input IN LISTS SHADER_PREPARATION_INPUTS)
    file(SHA256 "${shader_input}" shader_digest)
    string(APPEND SHADER_PREPARATION_FINGERPRINT "${shader_digest}\n")
endforeach()
string(SHA256 SHADER_PREPARATION_DIGEST "${SHADER_PREPARATION_FINGERPRINT}")
file(GENERATE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/shader_preparation_build.h"
    CONTENT "#pragma once\ninline constexpr char kShaderPreparationBuild[] = \"${SHADER_PREPARATION_DIGEST}\";\n")
target_include_directories(darkwatch_xbe PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
add_executable(darkwatch_hd_ui_builder src/tools/prepare_hd_ui.cpp)
# Network co-op guest: sends a controller to a hosting game as player 2.
add_executable(darkwatch_coop_client src/tools/coop_client.cpp src/common/coop_video.cpp)
target_include_directories(darkwatch_coop_client PRIVATE src)
# Media Foundation's H.264 encoder (host) and decoder (client) for the guest view.
set(COOP_VIDEO_LIBRARIES mfplat mfuuid wmcodecdspuuid strmiids ole32 oleaut32)
target_link_libraries(darkwatch_coop_client PRIVATE SDL3::SDL3-static ws2_32 winmm ${COOP_VIDEO_LIBRARIES})
target_link_libraries(darkwatch_xbe PRIVATE ${COOP_VIDEO_LIBRARIES})
# Native narrow-path APIs must accept Unicode Windows profile names (Windows 10 1903+).
foreach(native_target darkwatch_xbe darkwatch_hd_ui_builder darkwatch_coop_client)
    target_link_options(${native_target} PRIVATE "LINKER:/manifest:embed"
        "LINKER:/manifestinput:${CMAKE_CURRENT_SOURCE_DIR}/src/common/windows.manifest")
    set_property(TARGET ${native_target} APPEND PROPERTY LINK_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/src/common/windows.manifest")
endforeach()
target_include_directories(darkwatch_hd_ui_builder PRIVATE src)
target_link_libraries(darkwatch_hd_ui_builder PRIVATE tomlplusplus::tomlplusplus windowscodecs ole32)
file(GLOB_RECURSE HD_UI_RESTORED_SOURCES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/hd_ui/*.png" "${CMAKE_CURRENT_SOURCE_DIR}/hd_ui/*.toml")
file(GENERATE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/hd-ui-inputs.txt" CONTENT "${HD_UI_RESTORED_SOURCES}\n")
add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/hd-ui.pack"
    COMMAND darkwatch_hd_ui_builder "${CMAKE_CURRENT_SOURCE_DIR}/../game_files/packfile.pck" "${CMAKE_CURRENT_BINARY_DIR}/hd-ui.pack" "${CMAKE_CURRENT_SOURCE_DIR}/hd_ui"
    DEPENDS darkwatch_hd_ui_builder "${CMAKE_CURRENT_SOURCE_DIR}/../game_files/packfile.pck"
        "${CMAKE_CURRENT_BINARY_DIR}/hd-ui-inputs.txt" ${HD_UI_RESTORED_SOURCES}
    VERBATIM)
add_custom_target(darkwatch_hd_ui_assets DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/hd-ui.pack")
add_dependencies(darkwatch_xbe darkwatch_hd_ui_assets)
# Keep diagnostic and release binaries separate; symbols stay local for crash triage.
if(DARKWATCH_RELEASE)
    target_compile_definitions(darkwatch_xbe PRIVATE XBE_RELEASE)
    # Keep private symbols useful without embedding a developer's workspace path.
    target_link_options(darkwatch_xbe PRIVATE -Wl,/pdbaltpath:darkwatch_xbe.pdb)
    target_link_options(darkwatch_hd_ui_builder PRIVATE -Wl,/pdbaltpath:darkwatch_hd_ui_builder.pdb)
else()
    target_compile_options(darkwatch_xbe PRIVATE -UNDEBUG)
endif()
# The original pad callback supplies gated UI navigation through SDL.
target_compile_definitions(darkwatch_xbe PRIVATE IMGUI_IMPL_WIN32_DISABLE_GAMEPAD)
