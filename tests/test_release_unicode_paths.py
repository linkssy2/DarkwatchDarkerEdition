"""Exercise the native runtime's path conversions without launching the game."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows process code page contract")
class ReleaseUnicodePathsTests(unittest.TestCase):
    def test_manifest_preserves_native_file_paths_and_crt_arguments(self):
        compiler = str(Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/Llvm/x64/bin/clang++.exe"))
        if not Path(compiler).is_file():
            self.skipTest("The native Clang/MSVC toolchain is required")
        sdk_tools = sorted(Path("C:/Program Files (x86)/Windows Kits/10/bin").glob("10.*/x64/mt.exe"))
        if not sdk_tools:
            self.skipTest("The Windows SDK manifest tool is required")
        environment = dict(os.environ, PATH=str(sdk_tools[-1].parent) + os.pathsep + os.environ.get("PATH", ""))
        with tempfile.TemporaryDirectory(prefix="darkwatch-path-") as temporary:
            root = Path(temporary)
            source = root / "paths.cpp"
            source.write_text(r'''
#include <windows.h>
#include <filesystem>
#include <fstream>
#include <cstdio>
#include <string>
#include <iostream>
#include <toml++/toml.hpp>
int main(int argc, char** argv) {
    namespace fs = std::filesystem;
    wchar_t module[32768]{};
    GetModuleFileNameW(nullptr, module, 32768);
    fs::path directory = fs::path(module).parent_path();
    bool narrow=false, roundtrip=false, crt=false, stream=false, toml=false, args=false;
    try {
        std::string name=directory.string();
        auto utf8=directory.u8string();
        narrow=name==std::string(reinterpret_cast<const char*>(utf8.data()),utf8.size());
        roundtrip=fs::path(name)==directory;
        fs::path file=directory / L"\u4fdd\u5b58-\u0416.toml";
        { std::ofstream write(file); write<<"value = 37\n"; }
        auto path=file.string();
        if (FILE* f=std::fopen(path.c_str(),"rb")) {crt=std::fgetc(f)=='v'; std::fclose(f);}
        { std::ifstream read(path); std::string line; stream=bool(std::getline(read,line))&&line=="value = 37"; }
        toml=toml::parse_file(path)["value"].value_or(0)==37;
        args=argc==2 && std::string(argv[1])==name;
    } catch(...) {}
    std::cout<<"{\"codepage\":"<<GetACP()<<",\"narrow_utf8\":"<<narrow
             <<",\"roundtrip\":"<<roundtrip<<",\"fopen\":"<<crt
             <<",\"ifstream\":"<<stream<<",\"toml\":"<<toml<<",\"arguments\":"<<args<<"}\n";
    return 0;
}
''', encoding="utf-8")
            include = ROOT / "build/xbexbe/_deps/tomlplusplus-src/include"
            manifest = ROOT / "xbexbe/src/common/windows.manifest"
            reports = {}
            for mode in ("before", "utf8"):
                # Cross-script and non-BMP characters expose an ANSI fallback on English Windows.
                folder = root / (mode + "-caf\u00e9-\u65e5\u672c-\u0416-\U0001f319")
                folder.mkdir()
                redist = Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Redist/MSVC/14.44.35112/x64/Microsoft.VC143.CRT")
                for library in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
                    shutil.copy2(redist / library, folder / library)
                exe = folder / "paths.exe"
                command = [compiler, "-std=c++20", "-O2", "-DNDEBUG", "-march=x86-64-v2", "-fuse-ld=lld",
                           "-I", str(include), str(source), "-o", str(exe)]
                if mode == "utf8":
                    command += ["-Xlinker", "/manifest:embed", "-Xlinker", "/manifestinput:" + str(manifest)]
                compiled = subprocess.run(command, capture_output=True, text=True, env=environment)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                checked = subprocess.run([str(exe), str(folder)], capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)
                reports[mode] = json.loads(checked.stdout)
            self.assertEqual(reports["utf8"], dict(codepage=65001, narrow_utf8=1, roundtrip=1,
                                                 fopen=1, ifstream=1, toml=1, arguments=1))
            if reports["before"]["codepage"] != 65001:
                self.assertEqual(reports["before"]["narrow_utf8"], 0)
            evidence = os.environ.get("DARKWATCH_UNICODE_EVIDENCE")
            if evidence:
                destination = Path(evidence)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
