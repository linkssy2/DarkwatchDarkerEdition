"""Real temporary files exercise the title-owned atomic profile store, never the game."""
from pathlib import Path
import hmac
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"


def string(value):
    return struct.pack("<H", len(value)) + value


def profile(player, inventory=b"items", history_count=2):
    data = b"FORP\x05\0\0\0" + bytes(6) + string(b"Default") + bytes(13) + string(player) + bytes(6)
    for _ in range(2):
        data += b"TATS\x02\0\0\0" + struct.pack("<I", 1)
        data += struct.pack("<I4sI", 0, b"Test", 5) + bytes(84)
    data += bytes(24) + b"\0\1" + struct.pack("<H", history_count)
    for i in range(history_count):
        data += struct.pack("<I", i % 17) + string(b"checkpoint")
        data += struct.pack("<III", 3, 4, len(inventory)) + inventory
    return data


def signed(payload):
    return payload + hmac.digest(bytes(16), payload, "sha1")


FIXTURE = r'''
#include "common/save_storage.h"
#include "kernel/crypto.h"
#include <cassert>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif
namespace fs = std::filesystem;
using Bytes=std::vector<uint8_t>;
Bytes Raw(const fs::path& p){std::ifstream f(p,std::ios::binary);return {std::istreambuf_iterator<char>(f),{}};}
void Put(const fs::path& p,const Bytes& d){std::ofstream f(p,std::ios::binary);f.write((const char*)d.data(),d.size());assert(f);}
Bytes Sign(Bytes d){const auto size=d.size();d.resize(size+20);uint8_t key[16]{};crypto::Hmac(key,16,d.data(),size,nullptr,0,d.data()+size);return d;}
size_t Files(){size_t n=0;for(auto&e:fs::directory_iterator(".")){assert(e.path().filename().string().find(".tmp-")==std::string::npos);++n;}return n;}
int main(){
 using namespace darkwatch::saves;
 const auto first=Raw("first.bin"),second=Raw("second.bin"),pair=Raw("pair.bin"),large=Raw("large.bin");
 assert(Valid(first)&&Valid(second)&&Valid(pair)&&Valid(large));
 assert(Valid(Raw("maximum.bin"))&&!Valid(Raw("above-maximum.bin")));
 assert(Write("maximum",Raw("maximum.bin"))&&Raw("maximum")==Raw("maximum.bin"));
 assert(!Write("maximum",Raw("above-maximum.bin"))&&Raw("maximum")==Raw("maximum.bin"));
 assert(!Valid(Raw("triple.bin"))&&!Valid(Raw("bad-version.bin"))&&!Valid(Raw("bad-count.bin")));
 assert(!Valid(Raw("bad-prefix.bin"))&&!Valid(Raw("bad-history.bin"))&&!Valid(Raw("bad-length.bin")));
 assert(!Valid(Raw("bad-duplicate.bin"))&&!Valid(Raw("bad-record-version.bin"))&&!Valid(Raw("bad-id.bin")));
 assert(!Valid(Bytes(0x40001))&&!Valid(Bytes{}));
 auto corrupt=first;corrupt.back()^=1;assert(!Valid(corrupt));
 for(size_t n=0;n<first.size()-20;++n)assert(!Valid(Sign(Bytes(first.begin(),first.begin()+n))));
 auto trailing=Bytes(first.begin(),first.end()-20);trailing.push_back(1);assert(!Valid(Sign(trailing)));
 fs::path slot="Profile 1";auto bak=fs::path("Profile 1.bak");
 assert(Write(slot,first)&&Raw(slot)==first&&!fs::exists(bak));
 assert(Write(slot,second)&&Raw(slot)==second&&Raw(bak)==first);
 const auto stamp=fs::last_write_time(slot),backup_stamp=fs::last_write_time(bak);const auto count=Files();
 assert(Write(slot,second)&&fs::last_write_time(slot)==stamp&&fs::last_write_time(bak)==backup_stamp&&Files()==count);
 assert(!Write(slot,corrupt)&&Raw(slot)==second&&Raw(bak)==first&&Files()==count);
 Bytes read{9,8};bool recovered=true;assert(Read(slot,read,&recovered)&&read==second&&!recovered);
 Put(slot,Bytes(first.begin(),first.begin()+12));const auto damaged=Raw(slot);
 assert(Read(slot,read,&recovered)&&recovered&&read==first&&Raw(slot)==damaged&&Raw(bak)==first);
 assert(Write(slot,pair)&&Raw(slot)==pair&&Raw(bak)==first);
 Put(slot,Bytes{});assert(Read(slot,read,&recovered)&&recovered&&read==first&&Raw(slot).empty());
 assert(Write(slot,second)&&Raw(bak)==first&&Raw(slot)==second);
 Put(bak,Bytes{1,2});Put(slot,Bytes{3,4});read={9,8};
 assert(!Read(slot,read,&recovered)&&!recovered&&(read==Bytes{9,8})&&(Raw(slot)==Bytes{3,4}));
 Put(bak,first);fs::remove(slot);read={9,8};
 assert(!Read(slot,read,&recovered)&&!recovered&&(read==Bytes{9,8})&&Raw(bak)==first);
 assert(Write(slot,second)&&Raw(slot)==second&&Raw(bak)==first);
 fs::create_directory("directory");Put("directory.bak",first);
 assert(!Read("directory",read,&recovered)&&!recovered&&!Write("directory",second));
 assert(!Write("missing-parent/profile",first));
 // A blocked backup replacement must not replace the committed profile.
 fs::remove(bak);fs::create_directory(bak);Put(bak/"keep",Bytes{7});
 assert(!Write(slot,pair)&&Raw(slot)==second&&(Raw(bak/"keep")==Bytes{7}));Files();
 fs::remove(bak/"keep");fs::remove(bak);Put(bak,first);
#ifdef _WIN32
 // Open for reading but deny delete sharing, making final atomic rename fail.
 HANDLE held=CreateFileW(slot.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);
 assert(held!=INVALID_HANDLE_VALUE);
 assert(!Write(slot,pair)&&Raw(slot)==second&&Raw(bak)==second);Files();CloseHandle(held);
 assert(Write(slot,pair)&&Raw(slot)==pair&&Raw(bak)==second);
 held=CreateFileW(bak.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);
 assert(held!=INVALID_HANDLE_VALUE);
 assert(!Write(slot,first)&&Raw(slot)==pair&&Raw(bak)==second);Files();CloseHandle(held);
#endif
 // Invalid size never allocates beyond the limit; recovery leaves bad bytes intact.
 Put(slot,Bytes(kMaxFileBytes+1,0x42));Put(bak,first);
 assert(Read(slot,read,&recovered)&&recovered&&read==first&&fs::file_size(slot)==kMaxFileBytes+1);
 assert(Write(slot,second)&&Raw(slot)==second&&Raw(bak)==first);Files();
 std::cout<<"save storage: bounded native validation, one/two profiles, atomic replacement, last-good backup, corrupt-only recovery, deletion, directories and failed commits passed\n";
}
'''


class SaveStorageTests(unittest.TestCase):
    def test_actual_store(self):
        compiler = shutil.which("clang++") or shutil.which("g++")
        if not compiler:
            known = Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/Llvm/x64/bin/clang++.exe")
            compiler = str(known) if known.is_file() else None
        self.assertIsNotNone(compiler, "C++ compiler required")
        with tempfile.TemporaryDirectory(prefix="save-storage-", dir=ROOT / "build") as temporary:
            folder = Path(temporary)
            first, second = profile(b"Jericho"), profile(b"Cassidy")
            data = {"first": first, "second": second, "pair": first + second,
                    "large": profile(b"Jericho", bytes(4096), 18), "triple": first + second + first}
            remaining = 0x40000 - len(profile(b"Jericho", b"", 1))
            data["maximum"] = profile(b"Jericho", bytes(remaining), 1)
            data["above-maximum"] = profile(b"Jericho", bytes(remaining + 1), 1)
            bad = bytearray(first);struct.pack_into("<I", bad, 4, 4);data["bad-version"] = bad
            bank = first.index(b"TATS")
            bad = bytearray(first);struct.pack_into("<I", bad, bank + 8, 18);data["bad-count"] = bad
            bad = bytearray(first);struct.pack_into("<I", bad, bank + 20, 4);data["bad-record-version"] = bad
            bad = bytearray(first);struct.pack_into("<I", bad, bank + 12, 17);data["bad-id"] = bad
            second_bank = first.index(b"TATS", bank + 4)
            bad = bytearray(first);bad[second_bank + 16:second_bank + 20] = b"Diff";data["bad-prefix"] = bad
            bad = bytearray(first);struct.pack_into("<I", bad, bank + 8, 2)
            bad[bank + 108:bank + 108] = first[bank + 12:bank + 108];data["bad-duplicate"] = bad
            history = second_bank + 108 + 24
            bad = bytearray(first);bad[history] = 2;data["bad-history"] = bad
            bad = bytearray(first);struct.pack_into("<I", bad, history + 4 + 24, 0xffffffff);data["bad-length"] = bad
            for name, payload in data.items():
                (folder / (name + ".bin")).write_bytes(signed(payload))
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(FIXTURE, encoding="utf-8")
            command = [compiler, "-std=c++20", "-O1", "-I", str(SDK), "-I", str(ROOT / "xbexbe/src"),
                       str(source), str(ROOT / "xbexbe/src/common/save_storage.cpp"),
                       str(SDK / "kernel/crypto.cpp"), "-o", str(exe)]
            built = subprocess.run(command, capture_output=True, text=True, timeout=90)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=25)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            print(ran.stdout.strip())


if __name__ == "__main__":
    unittest.main()
