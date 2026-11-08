"""Production catalogue rejection, exact matching, startup fallback and host/guest encodings."""
from pathlib import Path
import json
import re
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
 CHECK(std::string(Text("5.1 Surround"))=="Envolvente 5.1");
 CHECK(std::string(Text("7.1 Surround"))=="Envolvente 7.1");
 CHECK(std::string(Text("SIGHT MODE"))=="APUNTAR");
 CHECK(std::string(Text("Hold"))=="Mantener"&&std::string(Text("Toggle"))=="Alternar");
 CHECK(std::string(Text("Hold to aim while pressed. Toggle to cycle sight mode with each press."))=="Mantener para apuntar mientras pulsas. Alternar para cambiar de modo de mira con cada pulsación.");
 for(const char* text:{"Active output: Stereo.","Active output: 5.1 Surround.","Active output: 7.1 Surround.",
     "7.1 unavailable on this device; playback will use 5.1.",
     "Surround unavailable. Set up 5.1 or 7.1 speakers, then restart."})CHECK(std::string(Text(text))!=text);
 CHECK(std::string(Text("QUIT TO DESKTOP"))=="SALIR DEL JUEGO"&&std::string(Guest("QUIT TO DESKTOP"))=="SALIR DEL JUEGO");
 CHECK(std::string(Text("Quit to desktop?"))=="\xC2\xBF" "Salir al escritorio?");
 const char* stable=Text("SUBTITLES");for(int i=0;i<100;++i)CHECK(stable==Text("subtitles"));
 for(const auto& row:copy){
  CHECK(std::strcmp(Text(row.english),row.spanish)==0);
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
 // Portuguese is a separate catalogue. An available Spanish install must never
 // mask a missing/corrupt Portuguese text resource or leak its previous strings.
 write(publicPack);
 toml::table pt{{"language",toml::table{{"text","pt-BR"}}}};
 Load(&pt);CHECK(!Initialize(root)&&!Translated()&&!Portuguese()&&!Spanish());
 CHECK(Translate("GEN_Test","Back").empty()&&std::string(Text("GRAPHICS"))=="GRAPHICS");
 Save(&saved);CHECK(saved["language"]["text"].value_or(std::string{})=="pt-BR"&&saved["video"]["width"].value_or(0)==1920);
 target=root/"language/pt-BR/language_text.bin";std::filesystem::create_directories(target.parent_path());
 const auto ptPack=PublicPack("GEN_Test","Back","Voltar");write(ptPack);
 CHECK(Initialize(root)&&Translated()&&Portuguese()&&!Spanish());
 CHECK(Translate("GEN_Test","Back")=="Voltar"&&Translate("GEN_Test","Changed").empty());
 CHECK(std::string(Text("CONTROLS"))=="CONTROLES"&&std::string(Text("SUBTITLES"))=="LEGENDAS");
 CHECK(std::string(Text("Hold"))=="Segurar"&&std::string(Text("Toggle"))=="Alternar");
 for(const auto& row:copy_portuguese){
  CHECK(std::strcmp(Text(row.english),row.portuguese)==0);
  std::string expected;
  for(const auto* p=reinterpret_cast<const unsigned char*>(row.portuguese);*p;){
   unsigned c=*p++;if(c>=128){CHECK(c==0xC2||c==0xC3);CHECK((*p&0xC0)==0x80);c=((c&31)<<6)|(*p++&63);}
   if(c>=0xE0&&c<=0xFC&&c!=0xF7)c-=32;expected+=char(c);
  }
  CHECK(std::string(Guest(row.english))==expected);
 }
 CHECK(std::string(Guest("Switch between Dynamite and Splitter Grenades.")).find("dispers\xC3o")!=std::string::npos);
 const char* ptStable=Text("SUBTITLES");for(int i=0;i<100;++i)CHECK(ptStable==Text("subtitles"));
 for(size_t size=0;size<ptPack.size();++size){
  write(ptPack.substr(0,size));CHECK(!Initialize(root)&&!Portuguese()&&!Spanish()&&!Translated());
  CHECK(Translate("GEN_Test","Back").empty()&&std::string(Text("SUBTITLES"))=="SUBTITLES");
 }
 write(ptPack+"x");CHECK(!Initialize(root)&&!Translated());
 write(ptPack);CHECK(Initialize(root)&&Portuguese());
 Load(&es);CHECK(Initialize(root)&&Spanish()&&!Portuguese()&&Translate("GEN_Test","Back")=="Atr\xC1s");
 Load(&pt);CHECK(Initialize(root)&&Portuguese()&&!Spanish()&&Translate("GEN_Test","Back")=="Voltar");
 // Requested locale codes never substitute another installed text or media pack.
 CHECK(std::string(Code())=="pt-BR"&&MediaDirectory(root).empty());
 std::filesystem::create_directories(root/"language/es/assets");
 CHECK(MediaDirectory(root)==root/"language/es/assets");
 auto localeTest=[&](const char* code,const auto& entries,auto translation){
  toml::table preference{{"language",toml::table{{"text",code}}}};
  Load(&preference);CHECK(std::string(Code())==code&&!Translated()&&MediaDirectory(root).empty());
  Save(&saved);CHECK(saved["language"]["text"].value_or(std::string{})==code);
  target=root/"language"/code/"language_text.bin";
  std::filesystem::create_directories(target.parent_path());
  std::filesystem::create_directories(target.parent_path()/"assets");
  CHECK(!Initialize(root)&&!Translated()&&MediaDirectory(root).empty());
  CHECK(std::string(Text("CONTROLS"))=="CONTROLS"&&Translate("GEN_Test","Back").empty());
  const auto data=PublicPack("GEN_Test","Back",code);write(data);
  CHECK(Initialize(root)&&Translated()&&!Spanish()&&!Portuguese());
  CHECK(MediaDirectory(root)==target.parent_path()/"assets");
  CHECK(Translate("GEN_Test","Back")==code&&Translate("GEN_Test","changed").empty());
  for(const auto& row:entries){
   const char* host=translation(row);CHECK(std::strcmp(Text(row.english),host)==0);
   std::string expected;
   for(const auto* p=reinterpret_cast<const unsigned char*>(host);*p;){
    unsigned c=*p++;if(c>=128){CHECK(c==0xC2||c==0xC3);CHECK((*p&0xC0)==0x80);c=((c&31)<<6)|(*p++&63);}
    if(c>=0xE0&&c<=0xFC&&c!=0xF7)c-=32;expected+=char(c);
   }
   CHECK(std::string(Guest(row.english))==expected);
  }
  const char* stable=Text("CONTROLS");CHECK(stable==Text("controls"));
  for(size_t i=0;i<data.size();++i){write(data.substr(0,i));CHECK(!Initialize(root)&&!Translated()&&MediaDirectory(root).empty());}
  write(data+"extra");CHECK(!Initialize(root)&&MediaDirectory(root).empty());
  write(data);CHECK(Initialize(root)&&Translated());
  std::filesystem::rename(target.parent_path()/"assets",target.parent_path()/"assets.saved");
  CHECK(MediaDirectory(root).empty()); // No Spanish-media fallback for disc languages.
  std::filesystem::rename(target.parent_path()/"assets.saved",target.parent_path()/"assets");
 };
 localeTest("fr",copy_french,[](const auto& r){return r.french;});
 localeTest("de",copy_german,[](const auto& r){return r.german;});
 CHECK(std::string(Guest("Changes gun and hand framing.")).front()==char(0xC4));
 CHECK(std::string(Guest("0% = off. 100% = original size.")).find(char(0xDF))!=std::string::npos);
 localeTest("it",copy_italian,[](const auto& r){return r.italian;});
 CHECK(std::string(Guest("DISPLAY MODE")).find(char(0xC0))!=std::string::npos);
 Load(&es);CHECK(Initialize(root)&&Spanish()&&MediaDirectory(root)==root/"language/es/assets");
 Load(&pt);CHECK(Initialize(root)&&Portuguese()&&MediaDirectory(root)==root/"language/es/assets");
 Load(&en);CHECK(Initialize(root)&&!Translated()&&MediaDirectory(root).empty()&&std::string(Code())=="en");
 for(const char* code:{"../es","PT-BR","FR","fr/assets","","zz"}){
  toml::table badCode{{"language",toml::table{{"text",code}}}};
  Load(&badCode);CHECK(std::string(Code())=="en"&&Initialize(root)&&!Translated()&&MediaDirectory(root).empty());
 }
 toml::table unknown{{"language",toml::table{{"text","pt"}}}};
 Load(&unknown);CHECK(Initialize(root)&&!Translated());
 // An invalid requested locale never applies a previously loaded catalogue.
 Load(&invalid);CHECK(Initialize(root)&&!Spanish());Load(nullptr);CHECK(Initialize(root)&&!Spanish());
 std::puts("PASS v1/v3 bounds/truncation/duplicates, exact contexts, six-locale selection/media isolation and 1500 stable custom host/guest strings");
}
'''

class LanguageTests(unittest.TestCase):
    def test_disc_language_ui_coverage_and_tokens(self):
        def rows(name):
            text = (ROOT / 'xbexbe/src/common' / ('language_' + name + '.h')).read_text(encoding='utf-8')
            return [tuple(json.loads('"' + cell + '"') for cell in row)
                    for row in re.findall(r'\{"((?:[^"\\]|\\.)*)", "((?:[^"\\]|\\.)*)"\}', text)]
        keys = [key for key, _ in rows('portuguese')]
        self.assertEqual(len(keys), 328)
        for locale, expected in {
            'portuguese': ('Ultrapanorâmico 21:9', 'Superultrapanorâmico 32:9', 'Tela ampla 16:10'),
            'french': ('Ultra-large 21:9', 'Super ultra-large 32:9', 'Écran large 16:10'),
            'german': ('Ultrabreit 21:9', 'Super-Ultrabreit 32:9', 'Breitbild 16:10'),
            'italian': ('Ultrapanoramico 21:9', 'Super ultrapanoramico 32:9', 'Panoramico 16:10'),
        }.items():
            labels = dict(rows(locale))
            self.assertEqual(labels['Ultrawide 21:9'], expected[0], locale)
            self.assertEqual(labels['Super Ultrawide 32:9'], expected[1], locale)
            self.assertEqual(labels['Widescreen 16:10'], expected[2], locale)
            for key in ('MENU ASPECT RATIO', 'Widescreen', 'Original 4:3',
                        'Menus, logos and loading artwork. Gameplay and movies are unchanged.'):
                self.assertIn(key, labels, locale)
        supported = set('¡¿ÀÁÂÄÇÈÉÊËÌÍÎÏÑÒÓÔÖÙÚÛÜß')
        for locale in ('french', 'german', 'italian'):
            translations = rows(locale)
            self.assertEqual([key for key, _ in translations], keys)
            self.assertEqual(len({key.lower() for key, _ in translations}), len(keys))
            for key, translated in translations:
                self.assertTrue(translated, (locale, key))
                self.assertEqual(re.findall(r'%[sdu]|\^\w+', key), re.findall(r'%[sdu]|\^\w+', translated), (locale, key))
                self.assertEqual(key.count('\n'), translated.count('\n'), (locale, key))
                for char in translated:
                    if ord(char) >= 128:
                        self.assertIn(char if char == 'ß' else char.upper(), supported, (locale, key, char))
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

