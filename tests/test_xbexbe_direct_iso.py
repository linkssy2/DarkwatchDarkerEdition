"""Exercise real ISO admission, prepared-file precedence and read-only guest I/O."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from test_xbexbe_async_file_io import HARNESS, ROOT, SDK
from test_xbexbe_language_files import DRIVER as LANGUAGE_DRIVER

TOML = ROOT / 'build/xbexbe/_deps/tomlplusplus-src/include'
XBE = b'release-fixture'
FILES = {'default.xbe': XBE, 'packfile.pck': b'Retail pack', 'audioDlg.pck': b'English disc dialogue',
         'Movies1.pck': b'Disc movie'}


def make_iso(path, files=FILES, partition=0):
    """Minimal real XDVDFS directory, with sector-aligned root payloads."""
    magic = b'MICROSOFT*XBOX*MEDIA'
    volume, table = bytearray(2048), bytearray()
    entries = list(files.items())
    for index, (name, content) in enumerate(entries):
        name = name.encode('ascii')
        size = (14 + len(name) + 3) & ~3
        next_entry = (len(table) + size) // 4 if index + 1 < len(entries) else 0
        table.extend(struct.pack('<HHIIBB', 0, next_entry, 40 + index, len(content), 0, len(name)))
        table.extend(name)
        table.extend(b'\0' * (size - 14 - len(name)))
    volume[:len(magic)] = volume[0x7ec:0x7ec + len(magic)] = magic
    struct.pack_into('<IIQ', volume, 0x14, 33, len(table), 1)
    with path.open('wb') as out:
        out.seek(partition + 32 * 2048)
        out.write(volume)
        out.write(table)
        for index, (_, content) in enumerate(entries):
            out.seek(partition + (40 + index) * 2048)
            out.write(content)


ADMISSION = r'''
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include "app/app.h"
#include "kernel/disc.h"
#include "core/log.h"
#define CHECK(x) do { if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);} } while(0)
static std::filesystem::path root;
static int dialogs=0;
static int WINAPI FixtureMessage(HWND,LPCWSTR,LPCWSTR,UINT type){CHECK(!(type&MB_YESNO));++dialogs;return IDYES;}
#define MessageBoxW FixtureMessage
#include "app/game_files.cpp"
#undef MessageBoxW
extern const char kImageSha1[]="FIXTURE_HASH";
extern const unsigned long long kImageSize=15;
namespace app {
const GameInfo kGame{.short_title=L"fixture"};
std::filesystem::path ExeDir(){return root;}
static bool preparing=false;
bool PreparingShaders(){return preparing;}
}
void logx::Write(Level,const char*,...){}
int main(int argc,char**argv){
 CHECK(argc==4);root=argv[1];const int expected=std::atoi(argv[2]);app::preparing=std::atoi(argv[3])!=0;
 app::GameFiles game;CHECK(app::FindGame(game)==(expected!=0));
 CHECK(dialogs==(expected||app::preparing?0:1));
 if(expected){CHECK(game.dir==root/"assets"&&game.xbe==std::vector<uint8_t>({'r','e','l','e','a','s','e','-','f','i','x','t','u','r','e'}));}
 CHECK((kernel::MountedDisc()!=nullptr)==(expected==1));
 if(expected==1){CHECK(kernel::MountedDisc()->Overrides()==std::vector<std::string>{"packfile.pck"});}
 std::puts("ISO admission result matched");
}
'''.replace('FIXTURE_HASH', hashlib.sha1(XBE).hexdigest())

FILE_DRIVER = r'''
static void Listing(const char* filename,uint64_t size){
 using namespace kernel;auto h=Open("D:\\",0x21);Name(filename);
 CHECK(Call(207,{h,0,0,0,0x220,0x800,512,1,0x400,1})==kSuccess);
 CHECK(R32(0x220)==kSuccess&&R32(0x224)==0x40+std::strlen(filename));
 CHECK(R64(0x828)==size&&R64(0x830)==((size+4095)&~4095ull));
 CHECK(R32(0x838)==0x80&&R32(0x83C)==std::strlen(filename));
 CHECK(!std::memcmp(memory+0x840,filename,std::strlen(filename)));
 CHECK(Call(207,{h,0,0,0,0x220,0x800,512,1,0x400,0})==kNoMoreFiles);
 CHECK(CloseHandle(h));Name((std::string("D:\\")+filename).c_str());
 CHECK(Call(210,{0x300,0x800})==kSuccess);
 CHECK(R64(0x820)==((size+4095)&~4095ull)&&R64(0x828)==size&&R32(0x830)==0x80);
}
int main(int argc,char**argv){
 using namespace kernel;CHECK(argc==2);std::filesystem::path root=argv[1],assets=root/"assets",es=root/"es";
 Write(assets/"packfile.pck","Prepared pack");Write(assets/"Movies1.pck","Stale local movie");
 Write(es/"packfile.pck","Spanish pack");Write(es/"audioDlg.pck","Spanish dialogue");
 MountDefaults(assets.string(),(root/"data").string());
 auto disc=std::make_unique<Disc>();std::string error;CHECK(disc->Open(root/"game.iso",error));
 disc->SetOverrides({"packfile.pck"});MountDisc(std::move(disc));
 Read("D:\\packfile.pck","Prepared pack");Read("D:\\PACKFILE.PCK","Prepared pack");
 Read("D:\\Movies1.pck","Disc movie");Read("D:\\audioDlg.pck","English disc dialogue");
 Listing("packfile.pck",13);Listing("Movies1.pck",10);Listing("audioDlg.pck",21);
 // Nested/traversing spellings never expand the declared root override scope.
 Read("D:\\.\\packfile.pck","Retail pack");
 std::vector<uint8_t> content;CHECK(ReadGameFile("D:\\packfile.pck",content));
 CHECK(std::string(content.begin(),content.end())=="Prepared pack");
 CHECK(!ResolvePath("D:\\packfile.pck",0).empty()&&ResolvePath("D:\\Movies1.pck",0).empty());
 // Prepared data is protected through every original write/delete/rename path.
 Name("D:\\packfile.pck");
 for(uint32_t access:{0x40000000u,0x10000000u,2u,4u,0x10u,0x100u,0x10000u,0x40000u,0x80000u})
  CHECK(Call(190,{0x200,access,0x300,0x220,0,0x80,1,1,0x20})==kAccessDenied);
 for(uint32_t disposition:{0u,2u,4u,5u})
  CHECK(Call(190,{0x200,0x80100080,0x300,0x220,0,0x80,1,disposition,0x20})==kAccessDenied);
 CHECK(Call(195,{0x300})==kAccessDenied);
 auto h=Open("D:\\packfile.pck",0x20);CHECK(FileFromHandle(h)->read_only);
 W64(0x280,0);CHECK(Call(236,{h,0,0,0,0x1000,0x2000,1,0x280})==kAccessDenied);
 CHECK(Rename(h,"E:\\moved.pck")==kAccessDenied);CHECK(CloseHandle(h));
 // Saves remain writable and never redirect into either overlay.
 CreateSymbolicLink("\\??\\E:","\\Device\\Harddisk0\\Partition1");
 const auto save=Resolve("E:\\packfile.pck",0);Write(save.host,"Save data");
 h=Open("E:\\packfile.pck",0x20);CHECK(!FileFromHandle(h)->read_only);
 CHECK(Rename(h,"D:\\packfile.pck")==kAccessDenied);CHECK(CloseHandle(h));
 Read("E:\\packfile.pck","Save data");
 SetGameFileOverlay(es.string());Read("D:\\packfile.pck","Spanish pack");
 Read("D:\\audioDlg.pck","Spanish dialogue");Read("D:\\Movies1.pck","Disc movie");
 Listing("packfile.pck",12);Listing("audioDlg.pck",16);Listing("Movies1.pck",10);
 CheckReadOnly();
 SetGameFileOverlay("");Read("D:\\packfile.pck","Prepared pack");
 // A deleted prepared file produces an ordinary missing-file result, never retail fallback.
 std::filesystem::remove(assets/"packfile.pck");Name("D:\\packfile.pck");
 CHECK(Call(190,{0x200,0x80100080,0x300,0x220,0,0x80,1,1,0x20})==kObjectNameNotFound);
 CHECK(!ReadGameFile("D:\\packfile.pck",content));
 h=Open("D:\\",0x21);Name("packfile.pck");
 CHECK(Call(207,{h,0,0,0,0x220,0x800,512,1,0x400,1})==kObjectNameNotFound);
 CHECK(R32(0x220)==kObjectNameNotFound&&R32(0x224)==0);CHECK(CloseHandle(h));
 // Ordinary developer ISO mounts have no prepared-file precedence.
 Write(assets/"packfile.pck","Prepared pack");
 disc=std::make_unique<Disc>();CHECK(disc->Open(root/"game.iso",error));MountDisc(std::move(disc));
 Read("D:\\packfile.pck","Retail pack");
 Listing("packfile.pck",11);
 MountDisc(nullptr);Read("D:\\packfile.pck","Prepared pack");Read("D:\\Movies1.pck","Stale local movie");
 std::puts("PASS real ISO + prepared + Spanish priority, metadata, host consumers, save isolation and write protection");
}
'''


class DirectIsoTests(unittest.TestCase):
    def compile(self, folder, name, source, release=False, file_service=False):
        compiler = shutil.which('clang++')
        if not compiler:
            self.skipTest('clang++ required')
        cpp, exe = folder / (name + '.cpp'), folder / (name + '.exe')
        cpp.write_text(source, encoding='utf-8')
        # This SDK reader needs only the disc filename, not translated functions.
        (folder / 'image_symbols.h').write_text('#pragma once\n#define IMAGE_XBE "default.xbe"\n', encoding='utf-8')
        cmd = [compiler, '-std=c++20', '-O1', '-fuse-ld=lld', '-I', str(SDK), '-I', str(TOML),
               '-I', str(folder), str(cpp), str(SDK / 'kernel/disc.cpp')]
        if release:
            cmd.append('-DXBE_RELEASE')
        if not file_service:
            cmd.append(str(SDK / 'kernel/crypto.cpp'))
        cmd.extend(['-o', str(exe)])
        built = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        return exe

    def run_native(self, exe, *args):
        run = subprocess.run([str(exe), *map(str, args)], text=True, capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run.stdout.strip()

    def test_explicit_iso_admission_release_and_diagnostic(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='iso-admission-') as tmp:
            folder = Path(tmp)
            root = folder / 'install'
            assets = root / 'assets'
            assets.mkdir(parents=True)
            (assets / 'default.xbe').write_bytes(XBE)
            (assets / 'packfile.pck').write_bytes(b'Prepared pack')
            iso = folder / 'disco-espa\u00f1ol.iso'
            make_iso(iso)
            marker = root / 'disc-source.toml'
            def receipt(path=iso, overrides=('packfile.pck',), schema=1):
                return ('schema_version = ' + str(schema) + '\npath = ' + json.dumps(str(path), ensure_ascii=False) +
                        '\noverrides = ' + json.dumps(list(overrides), ensure_ascii=False) + '\n')
            valid = receipt()
            invalid = ['invalid toml=', '', 'x' * 16385, receipt(schema=2), receipt(path='relative.iso'),
                       receipt(path=folder/'missing.iso'), receipt(overrides=['missing.pck']),
                       receipt(overrides=['packfile.pck', 'PACKFILE.PCK']), receipt(overrides=['../packfile.pck']),
                       receipt(overrides=['C:/packfile.pck']), receipt(overrides=['packfile.pck:stream']),
                       receipt(overrides=['packfile.pck.']), receipt(overrides=['packfile.pck ']),
                       receipt(overrides=['.']), receipt(overrides=['..']), receipt(overrides=['a\\b']),
                       receipt(overrides=['a\0b']), valid.replace('overrides = ["packfile.pck"]', 'overrides = 3')]
            cases = 0
            for release in (False, True):
                exe = self.compile(folder, 'release' if release else 'diagnostic', ADMISSION, release)
                marker.write_text(valid, encoding='utf-8')
                self.run_native(exe, root, 1, 0)
                cases += 1
                for text in invalid:
                    marker.write_text(text, encoding='utf-8')
                    self.run_native(exe, root, 0, 0)
                    self.run_native(exe, root, 0, 1)
                    cases += 2
                marker.write_text(valid, encoding='utf-8')
                (assets/'default.xbe').write_bytes(b'wrong')
                self.run_native(exe, root, 0, 0)
                (assets/'default.xbe').write_bytes(XBE)
                make_iso(iso, {**FILES, 'default.xbe': b'release-fixturX'})
                self.run_native(exe, root, 0, 0)
                make_iso(iso, {**FILES, 'default.xbe': b'wrong-size'})
                self.run_native(exe, root, 0, 0)
                make_iso(iso)
                marker.unlink()
                marker.mkdir()
                self.run_native(exe, root, 0, 0)
                marker.rmdir()
                self.run_native(exe, root, 2, 0)
                cases += 5
                # Full disc-layout support and Unicode ISO source both use the real SDK reader.
                make_iso(iso, partition=0x18300000)
                marker.write_text(valid, encoding='utf-8')
                self.run_native(exe, root, 1, 0)
                make_iso(iso)
                cases += 1
            print(f'PASS {cases} actual direct ISO admission cases (release and diagnostic)')

    def test_actual_file_priority_and_write_protection(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build', prefix='iso-files-') as tmp:
            folder = Path(tmp)
            make_iso(folder/'game.iso')
            helpers = LANGUAGE_DRIVER[:LANGUAGE_DRIVER.index('int main(')]
            exe = self.compile(folder, 'files', HARNESS + helpers + FILE_DRIVER, file_service=True)
            print(self.run_native(exe, folder))


if __name__ == '__main__':
    unittest.main()
