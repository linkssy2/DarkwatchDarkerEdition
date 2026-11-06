"""Disc-derived preview parser, atlas lifetime and real ImGui geometry checks."""
from pathlib import Path
import os
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
IMGUI = ROOT / 'build/xbexbe/_deps/imgui-src'
SDK = ROOT / 'third_party/XboxXBERecomp/runtime'


def pack():
    out = bytearray(b'DWCP0003' + struct.pack('<II', 3, 10))
    for model in range(10):
        out += struct.pack('<5If', model, 6, 2, 1, 2, 1.5)
        palette = bytes((0, 40, 230, 128)) + bytes(1020)  # BGRA, translucent red.
        out += struct.pack('<5IQ', 4, 4, 0, 1024, 16, 0) + palette + bytes(16)
        for _ in range(2):
            out += b''.join(struct.pack('<2fI', *uv, 0xffffffff) for uv in ((0., 0.), (1., 0.), (.5, 1.)))
        out += struct.pack('<10I', 0, 1, 2, 0, 0xffffffff, 3, 4, 5, 0, 0x80ffffff)
        for frame in range(2):
            for depth in (-.2, .2):
                for x, y in ((-.4, 0.), (.4, 0.), (0., 1.)):
                    out += struct.pack('<6f', x + frame * .05, y, depth, 0., 0., 1.)
    value = 14695981039346656037
    for byte in out:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return bytes(out) + struct.pack('<Q', value)


SOURCE = r'''
#include "common/character_preview.cpp"
#include <cstdio>
#include <cstdlib>
#include <chrono>
using namespace darkwatch;
#define CHECK(x) do { ++checks; if(!(x)) { std::fprintf(stderr,"line%d: %s\n",__LINE__,#x);return 90;} } while(0)
static unsigned checks=0;
static void Context() {
 ImGui::CreateContext();auto& io=ImGui::GetIO();io.IniFilename=nullptr;io.DisplaySize={1280,720};
 io.BackendFlags|=ImGuiBackendFlags_RendererHasVtxOffset;io.Fonts->AddFontDefault();
}
static ImDrawList* Frame() {
 ImGui::GetIO().DeltaTime=1.f/60;ImGui::NewFrame();ImGui::SetNextWindowPos({0,0});ImGui::SetNextWindowSize(ImGui::GetIO().DisplaySize);
 ImGui::Begin("preview",nullptr,ImGuiWindowFlags_NoDecoration|ImGuiWindowFlags_NoBackground);return ImGui::GetWindowDrawList();
}
static void EndFrame(){ImGui::End();ImGui::Render();}
static std::vector<uint8_t> Read(const char* path){std::ifstream f(path,std::ios::binary);return {std::istreambuf_iterator<char>(f),{}};}
static void Hash(std::vector<uint8_t>& data){auto h=hd::Hash({data.data(),data.size()-8});std::memcpy(data.data()+data.size()-8,&h,8);}
// Independent image of the actual ImGui geometry/atlas; not live GPU acceptance.
static bool Picture(const char* directory,unsigned frame){
 const int width=1280,height=720;std::vector<uint8_t> output(size_t(width)*height*4,20);
 unsigned char* tex;int tw,th;ImGui::GetIO().Fonts->GetTexDataAsRGBA32(&tex,&tw,&th);
 auto edge=[](ImVec2 a,ImVec2 b,ImVec2 p){return(b.x-a.x)*(p.y-a.y)-(b.y-a.y)*(p.x-a.x);};
 for(auto* list:ImGui::GetDrawData()->CmdLists)for(const auto& command:list->CmdBuffer){
  if(command.UserCallback)continue;
  for(unsigned index=0;index+2<command.ElemCount;index+=3){
   ImDrawVert v[3];for(unsigned k=0;k<3;++k)v[k]=list->VtxBuffer[list->IdxBuffer[command.IdxOffset+index+k]+command.VtxOffset];
   const float area=edge(v[0].pos,v[1].pos,v[2].pos);if(std::abs(area)<.00001f)continue;
   int left=std::max({0,int(command.ClipRect.x),int(std::floor(std::min({v[0].pos.x,v[1].pos.x,v[2].pos.x})))});
   int top=std::max({0,int(command.ClipRect.y),int(std::floor(std::min({v[0].pos.y,v[1].pos.y,v[2].pos.y})))});
   int right=std::min({width,int(command.ClipRect.z),int(std::ceil(std::max({v[0].pos.x,v[1].pos.x,v[2].pos.x})))});
   int bottom=std::min({height,int(command.ClipRect.w),int(std::ceil(std::max({v[0].pos.y,v[1].pos.y,v[2].pos.y})))});
   for(int y=top;y<bottom;++y)for(int x=left;x<right;++x){
    const ImVec2 p{float(x)+.5f,float(y)+.5f};float weights[]{edge(v[1].pos,v[2].pos,p)/area,edge(v[2].pos,v[0].pos,p)/area,edge(v[0].pos,v[1].pos,p)/area};
    if(weights[0]<0||weights[1]<0||weights[2]<0)continue;
    float u=0,w=0,tint[4]{};for(unsigned k=0;k<3;++k){u+=v[k].uv.x*weights[k];w+=v[k].uv.y*weights[k];for(unsigned lane=0;lane<4;++lane)tint[lane]+=float(v[k].col>>(lane*8)&255)*weights[k]/255;}
    u=u*tw-.5f;w=w*th-.5f;int ix=int(std::floor(u)),iy=int(std::floor(w));float fx=u-ix,fy=w-iy,color[4]{};
    for(int sy=0;sy<2;++sy)for(int sx=0;sx<2;++sx){const auto* q=tex+(std::clamp(iy+sy,0,th-1)*tw+std::clamp(ix+sx,0,tw-1))*4;float weight=(sx?fx:1-fx)*(sy?fy:1-fy);for(unsigned lane=0;lane<4;++lane)color[lane]+=q[lane]*weight;}
    float alpha=color[3]*tint[3]/255;auto* d=output.data()+(y*width+x)*4;
    for(unsigned lane=0;lane<3;++lane)d[2-lane]=uint8_t(std::clamp(color[lane]*tint[lane]*alpha+d[2-lane]*(1-alpha),0.f,255.f));d[3]=255;
   }
  }
 }
 unsigned visible[10]{};for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x){auto* p=output.data()+(y*width+x)*4;if(std::max({p[0],p[1],p[2]})>40)++visible[(y/360)*5+x/256];}
 bool readable=true;std::printf("preview%u colored pixels",frame);
 for(auto count:visible){std::printf(" %u",count);readable&=count>500;}std::puts("");
 if(!directory)return readable;
 std::filesystem::create_directories(directory);std::ofstream file(std::filesystem::path(directory)/("preview-"+std::to_string(frame)+".bmp"),std::ios::binary);
 uint8_t header[54]{};header[0]='B';header[1]='M';auto set=[&](unsigned at,uint32_t value){std::memcpy(header+at,&value,4);};
 set(2,54+output.size());set(10,54);set(14,40);set(18,width);set(22,uint32_t(-height));header[26]=1;header[28]=32;
 file.write((char*)header,54);file.write((char*)output.data(),output.size());
 return readable&&bool(file);
}
int main(int argc,char** argv){
 CHECK(argc>=2);auto data=Read(argv[1]);std::array<preview::Model,settings::kCharacterCount> models;
 CHECK(preview::Color(0xff000000,0xffffffff,.72f)==0xffb8b8b8);
 CHECK(preview::Color(0x80ffce9c,0xffffffff,.72f)==0x80ffceb8);
 CHECK(preview::Load(data,models));CHECK(models[0].poses.size()==12);CHECK(models[2].frame_count==2);
 for(const char* magic:{"DWCP0001","DWCP0002"}){auto old_format=data;std::memcpy(old_format.data(),magic,8);Hash(old_format);CHECK(!preview::Load(old_format,models));}
 auto incomplete=data;uint32_t old_count=3;std::memcpy(incomplete.data()+12,&old_count,4);Hash(incomplete);CHECK(!preview::Load(incomplete,models));
 auto invalid=data;invalid.back()^=1;CHECK(!preview::Load(invalid,models));
 for(size_t n: {size_t(0),size_t(8),size_t(24),data.size()-1})CHECK(!preview::Load({data.data(),n},models));
 invalid=data;uint32_t enormous=0xffffffff;std::memcpy(invalid.data()+20,&enormous,4);Hash(invalid);CHECK(!preview::Load(invalid,models));
 invalid=data;float nan=std::numeric_limits<float>::quiet_NaN();std::memcpy(invalid.data()+36,&nan,4);Hash(invalid);CHECK(!preview::Load(invalid,models));
 invalid=data;const uint32_t beyond=6;std::memcpy(invalid.data()+40+28+1040+72,&beyond,4);Hash(invalid);CHECK(!preview::Load(invalid,models));
 invalid=data;float baduv=2;std::memcpy(invalid.data()+40+28+1040,&baduv,4);Hash(invalid);CHECK(!preview::Load(invalid,models));
 // Only the selected allowlisted HD file is required, and its checksum is mandatory.
 const auto* asset=&kGameplayAssets[0];for(const auto& candidate:kGameplayAssets)if(uint64_t(candidate.hd_width)*candidate.hd_height<uint64_t(asset->hd_width)*asset->hd_height)asset=&candidate;
 const auto hd_directory=std::filesystem::path(argv[1]).parent_path()/"hd";std::filesystem::create_directory(hd_directory);
 std::vector<uint8_t> hdbytes(32);std::memcpy(hdbytes.data(),"DWGAME02",8);uint32_t hdheader[]{asset->hd_width,asset->hd_height,asset->hd_levels,asset->bytes};
 std::memcpy(hdbytes.data()+8,hdheader,16);std::memcpy(hdbytes.data()+24,&asset->native_hash,8);
 for(unsigned level=0;level<asset->hd_levels;++level)hdbytes.resize(hdbytes.size()+size_t(std::max(asset->hd_width>>level,1u))*std::max(asset->hd_height>>level,1u)*4,255);
 hdbytes.resize(hdbytes.size()+8);Hash(hdbytes);const auto hdfile=hd_directory/asset->file;
 {std::ofstream f(hdfile,std::ios::binary);f.write((char*)hdbytes.data(),hdbytes.size());}
 gpu::TextureReplacement replacement;CHECK(GameplayTextures::LoadPreviewByNativeHash(hd_directory,asset->native_hash,replacement));
 CHECK(replacement.width==asset->hd_width&&replacement.height==asset->hd_height);CHECK(!GameplayTextures::LoadPreviewByNativeHash(hd_directory,0,replacement));
 hdbytes.back()^=1;{std::ofstream f(hdfile,std::ios::binary);f.write((char*)hdbytes.data(),hdbytes.size());}
 CHECK(!GameplayTextures::LoadPreviewByNativeHash(hd_directory,asset->native_hash,replacement));
 Context();auto* atlas=ImGui::GetIO().Fonts;const int old=atlas->CustomRects.Size;
 CHECK(!preview::Initialize(atlas,"absent-preview.pack"));CHECK(atlas->CustomRects.Size==old);
 CHECK(preview::Initialize(atlas,argv[1]));CHECK(atlas->CustomRects.Size==old+settings::kCharacterCount);
 CHECK(preview::Initialize(atlas,argv[1]));CHECK(atlas->CustomRects.Size==old+settings::kCharacterCount);
 CHECK(preview::Finalize());CHECK(preview::Owned());
 unsigned char* pixels;int width,height;atlas->GetTexDataAsRGBA32(&pixels,&width,&height);
 for(const auto& m:preview::state.models)for(const auto& t:m.textures){
  const auto* c=atlas->GetCustomRectByIndex(t.native.cell);
  for(unsigned y=0;y<c->Height;y++)for(unsigned x=0;x<c->Width;x++){
   auto* p=pixels+((c->Y+y)*width+c->X+x)*4;CHECK(p[0]==230&&p[1]==40&&p[2]==0&&p[3]==128);
  }
 }
 atlas->SetTexID(reinterpret_cast<ImTextureID>(uintptr_t(123)));CHECK(!preview::Finalize());
 auto* draw=Frame();auto before=draw->VtxBuffer.Size;
 CHECK(preview::Draw(settings::Character::Jericho,{50,60},{400,650},0,false));CHECK(draw->VtxBuffer.Size==before+6);
 const auto vertex=draw->VtxBuffer[before];CHECK(vertex.pos.x>=50&&vertex.pos.x<=400&&vertex.pos.y>=60&&vertex.pos.y<=650);
 // The rear triangle is submitted first; depth sorting retains material alpha.
 CHECK((vertex.col>>24)==255);CHECK((draw->VtxBuffer[before+3].col>>24)==128);
 auto uv=vertex.uv;CHECK(uv.x>0&&uv.x<1&&uv.y>0&&uv.y<1);
 CHECK(preview::Draw(settings::Character::Jericho,{50,60},{400,650},.375,false));CHECK(draw->VtxBuffer[before+6].pos.x!=vertex.pos.x);
 for(unsigned id=0;id<settings::kCharacterCount;++id)CHECK(preview::Draw(settings::Character(id),{0,0},{200,200},0));
 CHECK(!preview::Draw(settings::Character(settings::kCharacterCount),{0,0},{200,200},0));
 CHECK(!preview::Draw(settings::Character::Jericho,{0,0},{0,200},0));
 CHECK(!preview::Draw(settings::Character::Jericho,{0,0},{200,200},std::numeric_limits<double>::infinity()));
 EndFrame();
 // Pixel-space projection must apply one uniform scale at every output aspect.
 // Both co-op preview panels stay centered in the same 16:9-sized host menu.
 std::vector<ImVec2> reference;
 for(auto display:{ImVec2{1280,720},{2560,1440},{2560,1080},{3440,1440},{3840,1600},{5120,1440}}){
  ImGui::GetIO().DisplaySize=display;const float scale=display.y/720.f;
  for(float side:{-1.f,1.f}){
   draw=Frame();before=draw->VtxBuffer.Size;
   const ImVec2 center{display.x/2+side*240*scale,display.y/2};
   CHECK(preview::Draw(settings::Character::Jericho,{center.x-175*scale,center.y-295*scale},{center.x+175*scale,center.y+295*scale},.375,false));
   CHECK(draw->VtxBuffer.Size==before+6);
   for(int n=0;n<6;++n){const auto pos=draw->VtxBuffer[before+n].pos;const ImVec2 normalized{(pos.x-center.x)/scale,(pos.y-center.y)/scale};
    if(reference.size()<6)reference.push_back(normalized);
    else CHECK(std::abs(normalized.x-reference[n].x)<.001f&&std::abs(normalized.y-reference[n].y)<.001f);
   }
   EndFrame();
  }
 }
 ImGui::GetIO().DisplaySize={1280,720};
 atlas->SetTexID(nullptr);atlas->Clear();atlas->AddFontDefault();CHECK(!preview::Owned());
 CHECK(preview::Initialize(atlas,argv[1]));CHECK(preview::Finalize());atlas->SetTexID(reinterpret_cast<ImTextureID>(uintptr_t(124)));
 draw=Frame();CHECK(preview::Draw(settings::Character::SpectralCassidy,{0,0},{400,650},25));EndFrame();
 ImGui::DestroyContext();Context();atlas=ImGui::GetIO().Fonts;atlas->Build();atlas->SetTexID(reinterpret_cast<ImTextureID>(uintptr_t(125)));
 draw=Frame();CHECK(!preview::Draw(settings::Character::Cassidy,{0,0},{400,650},0));EndFrame();ImGui::DestroyContext();preview::Reset();
 if(argc>2){
  Context();atlas=ImGui::GetIO().Fonts;auto loaded=std::chrono::steady_clock::now();CHECK(preview::Initialize(atlas,argv[2],argc>3?argv[3]:""));CHECK(preview::Finalize());
  unsigned hd_count=0;for(const auto& model:preview::state.models)for(const auto& texture:model.textures)hd_count+=texture.hd.cell>=0;
  std::printf("actual initialize %.3fms; %u HD materials\n",std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-loaded).count(),hd_count);
  if(argc>3)CHECK(hd_count>0);
  std::printf("actual atlas %dx%d\n",atlas->TexWidth,atlas->TexHeight);
  atlas->SetTexID(reinterpret_cast<ImTextureID>(uintptr_t(126)));double milliseconds=0;size_t total=0;
  for(unsigned frame=0;frame<120;frame++){
   auto start=std::chrono::steady_clock::now();
   draw=Frame();for(unsigned id=0;id<settings::kCharacterCount;id++){const float x=(id%5)*256.f,y=(id/5)*360.f;CHECK(preview::Draw(settings::Character(id),{x, y+10},{x+246,y+350},frame/6.));}
   for(const auto& v:draw->VtxBuffer){CHECK(std::isfinite(v.pos.x)&&std::isfinite(v.pos.y)&&v.uv.x>=0&&v.uv.x<=1&&v.uv.y>=0&&v.uv.y<=1);}
   total+=draw->VtxBuffer.Size;EndFrame();milliseconds+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
   if(frame==0||frame==60)CHECK(Picture(std::getenv("DARKWATCH_PREVIEW_IMAGES"),frame));
  }
  std::printf("actual pack 360-degree sampled draw %.3fms/frame for ten previews; %zu vertices\n",milliseconds/120,total);
  ImGui::DestroyContext();preview::Reset();
 }
 std::printf("character preview passed %u checks\n",checks);
}
'''


class CharacterPreviewTests(unittest.TestCase):
    def test_parser_atlas_and_actual_imgui_draws(self):
        compiler = shutil.which('clang++') or r'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\Llvm\x64\bin\clang++.exe'
        with tempfile.TemporaryDirectory(prefix='character-preview-', dir=ROOT / 'build') as directory:
            folder = Path(directory)
            source, executable, fixture = folder/'test.cpp', folder/'test.exe', folder/'synthetic.pack'
            source.write_text(SOURCE)
            fixture.write_bytes(pack())
            command = [compiler, '-std=c++20', '-O2', '-fuse-ld=lld', '-I', str(ROOT/'xbexbe/src'),
                       '-I', str(SDK), '-I', str(IMGUI), str(source)]
            command += [str(IMGUI/f) for f in ('imgui.cpp', 'imgui_draw.cpp', 'imgui_widgets.cpp', 'imgui_tables.cpp')]
            result = subprocess.run(command+['-o',str(executable)], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            args = [str(executable),str(fixture)]
            if os.environ.get('DARKWATCH_PREVIEW_PACK'):
                args.append(os.environ['DARKWATCH_PREVIEW_PACK'])
                if os.environ.get('DARKWATCH_PREVIEW_HD'):
                    args.append(os.environ['DARKWATCH_PREVIEW_HD'])
            result = subprocess.run(args, capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main()
