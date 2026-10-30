"""Production catalogue rejection, exact matching, startup fallback and host/guest encodings."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "common/language.cpp"
#include <cstdio>
#include <cstdlib>
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);}}while(0)
using namespace darkwatch::language;
static std::string Pack(std::string key="GEN_Test",std::string original="Back",std::string translated="Atr\xC1s") {
 std::string result="DWES0001";
 auto number=[&](unsigned n){for(unsigned i=0;i<4;++i)result+=char(n>>(i*8));};
 number(1);number(unsigned(key.size()));number(unsigned(original.size()));number(unsigned(translated.size()));
 return result+key+original+translated;
}
static std::string PublicPack(std::string key="GEN_Test",std::string original="Back",std::string translated="Atr\xC1s") {
 std::string result="DWES0003";
 auto number=[&](unsigned n){for(unsigned i=0;i<4;++i)result+=char(n>>(i*8));};
 const auto identity=ContextId(NativeKey(key),original);number(1);number(unsigned(identity));number(unsigned(identity>>32));number(unsigned(translated.size()));
 return result+translated;
}
int main(){
 auto root=std::filesystem::current_path();auto target=root/"language/es/language_text.bin";
 std::filesystem::create_directories(target.parent_path());
 auto write=[&](const std::string& data){std::ofstream f(target,std::ios::binary|std::ios::trunc);f.write(data.data(),data.size());};
 toml::table en{{"language",toml::table{{"text","en"}}}},es{{"language",toml::table{{"text","es"}}}},invalid{{"language",toml::table{{"text",42}}}};
 Load(&en);CHECK(Initialize(root)&&!Spanish()&&std::string(Text("GRAPHICS"))=="GRAPHICS");
 CHECK(std::string(Guest("AUDIO"))=="AUDIO"&&std::string(Text("AUDIO"))=="AUDIO");
 Load(&es);CHECK(!Initialize(root)&&!Spanish());toml::table saved{{"video",toml::table{{"width",1920}}}};Save(&saved);CHECK(saved["language"]["text"].value_or(std::string{})=="es"&&saved["video"]["width"].value_or(0)==1920);
 write(Pack());CHECK(Initialize(root)&&Spanish());
 CHECK(Translate("GEN_Test","Back")=="Atr\xC1s");CHECK(Translate("GEN_Test","Changed").empty());
 CHECK(Translate("Other","Back").empty()&&Translate("gen_test","Back")=="Atr\xC1s");
 CHECK(std::string(Text("GRAPHICS"))=="GR\xC3\x81" "FICOS");CHECK(std::string(Guest("Graphics"))=="GR\xC1" "FICOS");
 CHECK(std::string(Guest("CONTROLS"))=="CONTROLES");
 CHECK(std::string(Guest("AUDIO"))=="AUDIO"&&std::string(Text("AUDIO"))=="AUDIO");
 CHECK(std::string(Text("Unbound"))=="Sin asignar");CHECK(std::string(Text("Never translated"))=="Never translated");
 CHECK(std::string(Text("QUIT TO DESKTOP"))=="SALIR DEL JUEGO"&&std::string(Guest("QUIT TO DESKTOP"))=="SALIR DEL JUEGO");
 CHECK(std::string(Text("Quit to desktop?"))=="\xC2\xBF" "Salir al escritorio?");
 const char* stable=Text("SUBTITLES");for(int i=0;i<100;++i)CHECK(stable==Text("subtitles"));
 for(const auto& row:copy){
  CHECK(Text(row.english)!=row.english);
  const char* guest=Guest(row.english);CHECK(std::strlen(guest)<=std::strlen(Text(row.english)));
  // Every host glyph used by our copy is ASCII or Spanish Latin-1 with an atlas cell.
  for(const auto* p=reinterpret_cast<const unsigned char*>(Text(row.english));*p;){unsigned c=*p++;if(c>=128){CHECK(c==0xC2||c==0xC3);CHECK((*p&0xC0)==0x80);c=((c&31)<<6)|(*p++&63);CHECK(c==0xA1||c==0xBF||c==0xC1||c==0xC9||c==0xCD||c==0xD1||c==0xD3||c==0xDA||c==0xDC||c==0xE1||c==0xE9||c==0xED||c==0xF1||c==0xF3||c==0xFA||c==0xFC);}}
 }
 const std::string valid=Pack();
 for(size_t size=0;size<valid.size();++size){write(valid.substr(0,size));CHECK(!Initialize(root)&&!Spanish());CHECK(Translate("GEN_Test","Back").empty());}
 for(const auto& bad:{valid+"x",Pack(std::string(129,'a')),Pack("a","b",std::string(16385,'c')),Pack("a","b",""),Pack("a","b",std::string("x\0y",3)),Pack(std::string("a\0b",3)),std::string(8*1024*1024+1,'x')}){
  write(bad);CHECK(!Initialize(root)&&!Spanish());CHECK(std::string(Text("GRAPHICS"))=="GRAPHICS");
 }
 auto duplicate=valid;duplicate[8]=2;duplicate+=Pack("GEN_Test","Back","different").substr(12);write(duplicate);CHECK(!Initialize(root)&&!Spanish());
 auto identical=valid;identical[8]=2;identical+=valid.substr(12);write(identical);CHECK(Initialize(root)&&Spanish());
 // Public resources retain only context IDs and translated strings; private v1 stays readable.
 CHECK(ContextId(NativeKey("GEN_Test"),"Back")==0x7dd34ffb1b12a266ull);
 const auto publicPack=PublicPack();CHECK(publicPack.find("GEN_Test")==std::string::npos&&publicPack.find("Back")==std::string::npos);
 write(publicPack);CHECK(Initialize(root)&&Spanish()&&Translate("GEN_Test","Back")=="Atr\xC1s");
 CHECK(Translate("GEN_Test","Changed").empty()&&Translate("Other","Back").empty());
 for(size_t size=0;size<publicPack.size();++size){write(publicPack.substr(0,size));CHECK(!Initialize(root)&&!Spanish());}
 for(const auto& bad:{publicPack+"x",PublicPack("a","b",""),PublicPack("a","b",std::string(16385,'c')),PublicPack("a","b",std::string("x\0y",3))}){write(bad);CHECK(!Initialize(root)&&!Spanish());}
 auto conflict=publicPack;conflict[8]=2;conflict+=PublicPack("GEN_Test","Back","different").substr(12);write(conflict);CHECK(!Initialize(root)&&!Spanish());
 auto publicSame=publicPack;publicSame[8]=2;publicSame+=publicPack.substr(12);write(publicSame);CHECK(Initialize(root)&&Spanish());
 // V2 stored a one-way key-text hash which cannot be resolved from native IDs.
 auto v2=publicPack;v2.replace(0,8,"DWES0002");write(v2);CHECK(!Initialize(root)&&!Spanish());
 CHECK(Translate(NativeKey("GEN_Test"),"Back").empty());
 // An invalid requested locale never applies a previously loaded catalogue.
 Load(&invalid);CHECK(Initialize(root)&&!Spanish());Load(nullptr);CHECK(Initialize(root)&&!Spanish());
 std::puts("PASS v1/v3 catalogue bounds/truncation/duplicates, context identity, fallback, stable host/guest Spanish copy");
}
'''

class LanguageTests(unittest.TestCase):
    def test_catalogue_and_copy(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="language-", dir=ROOT / "build") as temporary:
            folder = Path(temporary)
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(SOURCE, encoding="utf-8")
            build = subprocess.run([compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(ROOT / "xbexbe/src"),
                "-I", str(ROOT / "build/xbexbe/_deps/tomlplusplus-src/include"), str(source), "-o", str(exe)],
                capture_output=True, text=True, timeout=90)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            print(run.stdout.strip())

if __name__ == "__main__":
    unittest.main()

