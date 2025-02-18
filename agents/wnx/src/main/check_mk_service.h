//
// check_mk_service.h : The file contains ONLY 'main' function and "root
// supplies"
//
#pragma once
#ifndef check_mk_service_h__
#define check_mk_service_h__
#include <cstdint>
#include <string_view>
namespace cma::cmdline {
// Command Line parameters for service

constexpr int kParamShift = 10;

constexpr std::string_view kInstallParam = "install";
constexpr std::string_view kRemoveParam = "remove";
constexpr std::string_view kLegacyTestParam = "test";

constexpr std::string_view kCheckParam = "check";
constexpr std::string_view kCheckParamSelf = "-self";
constexpr std::string_view kCheckParamMt = "-mt";
constexpr std::string_view kCheckParamIo = "-io";

constexpr std::string_view kRealtimeParam = "rt";
constexpr std::string_view kHelpParam = "help";
constexpr std::string_view kVersionParam = "version";

constexpr std::string_view kExecParam = "exec";             // runs as app
constexpr std::string_view kAdhocParam = "adhoc";           // runs as app
constexpr std::string_view kExecParamShowWarn = "-show";    // logging sub param
constexpr std::string_view kExecParamShowAll = "-showall";  // logging sub param

constexpr std::string_view kCvtParam = "convert";    // convert ini to yaml
constexpr std::string_view kCvtParamShow = "-show";  // logging sub param
constexpr const wchar_t* kSkypeParam = L"skype";     // hidden
constexpr std::string_view kPatchHashParam = "patch_hash";      // hidden
constexpr std::string_view kStopLegacyParam = "stop_legacy";    //
constexpr std::string_view kStartLegacyParam = "start_legacy";  //

constexpr std::string_view kUpgradeParam = "upgrade";      // upgrade LWA
constexpr std::string_view kUpgradeParamForce = "-force";  // upgrade LWA always

constexpr std::string_view kCapParam = "cap";            // install files
constexpr std::string_view kSectionParam = "section";    // dump section
constexpr std::string_view kSectionParamShow = "-show";  // logging sub param

constexpr std::string_view kShowConfigParam = "showconfig";  // show config

constexpr std::string_view kResetOhm = "resetohm";  // reset ohm as treasury

// Service name and Targeting
#if defined(CMK_SERVICE_NAME)
constexpr const char* const kServiceExeName = "check_mk_agent.exe";
#elif defined(CMK_TEST)
constexpr const char* const kServiceExeName = L"test";
#else
#error "Target not defined properly"
#endif

}  // namespace cma::cmdline
namespace cma {
// we want to test main function too.
int MainFunction(int argc, wchar_t const* Argv[]);
}  // namespace cma
#endif  // check_mk_service_h__
