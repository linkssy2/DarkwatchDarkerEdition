"""Real ImGui page, draft/apply/revert and guest-input separation, without a game launch."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/XboxXBERecomp/runtime"
IMGUI = ROOT / "build/xbexbe/_deps/imgui-src"
FIXTURE = r'''
#include <imgui.h>
#include <imgui_internal.h>
#include <map>
#include <string>
#include <fstream>
#include <cstdarg>
#include <cstring>
#include <vector>
static std::map<std::string,ImVec2> button_centers;
static std::map<std::string,ImVec4> field_bounds;
static std::map<std::string,std::string> combo_text;
static std::map<std::string,std::string> slider_formats;
static std::map<std::string,std::pair<int,int>> slider_ranges;
static std::vector<std::string> rendered_text;
static std::string active_msaa_text;
static bool probe_navigation=false,child_navigation_kept=true;
static std::map<std::string,int> child_outline_vertices,child_outline_indices,widget_outline_vertices;
namespace ImGui {
struct WidgetHighlightProbe {
 bool enabled; ImGuiWindow* window; ImGuiID previous_id; bool previous_hidden; int first_vertex;
 WidgetHighlightProbe(const char* label):enabled(probe_navigation&&(std::strcmp(label,"##display")==0||std::strcmp(label,"##mouse sensitivity")==0)){
  if(!enabled)return;
  window=GetCurrentWindow();previous_id=GImGui->NavId;previous_hidden=GImGui->NavDisableHighlight;
  GImGui->NavId=window->GetID(label);GImGui->NavDisableHighlight=false;first_vertex=window->DrawList->VtxBuffer.Size;
 }
 ~WidgetHighlightProbe(){
  if(!enabled)return;
  auto a=GetItemRectMin(),b=GetItemRectMax();int count=0;
  const auto ivory=GetColorU32(ImVec4(.94f,.94f,.91f,1));
  for(int i=first_vertex;i<window->DrawList->VtxBuffer.Size;++i){auto& v=window->DrawList->VtxBuffer[i];
   if(v.col==ivory&&(v.pos.x<a.x||v.pos.x>b.x||v.pos.y<a.y||v.pos.y>b.y))++count;}
  widget_outline_vertices[window->Name]=count;
  GImGui->NavId=previous_id;GImGui->NavDisableHighlight=previous_hidden;
 }
};
void ObservedEndChild(){
 if(!probe_navigation){EndChild();return;}
 auto* child=GetCurrentWindow();auto* parent=child->ParentWindow;const std::string name=child->Name;
 const auto previous_id=GImGui->NavId;const bool previous_hidden=GImGui->NavDisableHighlight;
 const auto flags=child->Flags;const auto child_flags=child->ChildFlags;
 GImGui->NavId=child->ChildId;GImGui->NavDisableHighlight=false;
 const int vertices=parent->DrawList->VtxBuffer.Size,indices=parent->DrawList->IdxBuffer.Size;
 EndChild();
 child_outline_vertices[name]=parent->DrawList->VtxBuffer.Size-vertices;
 child_outline_indices[name]=parent->DrawList->IdxBuffer.Size-indices;
 child_navigation_kept&=GImGui->LastItemData.ID==child->ChildId&&child->Flags==flags&&child->ChildFlags==child_flags&&
  !(child->Flags&ImGuiWindowFlags_NoNav)&&!(child->ChildFlags&ImGuiChildFlags_NavFlattened);
 GImGui->NavId=previous_id;GImGui->NavDisableHighlight=previous_hidden;
}
void ObservedTextUnformatted(const char* text,const char* end=nullptr){
 rendered_text.emplace_back(text,end?size_t(end-text):std::strlen(text));TextUnformatted(text,end);
}
void ObservedTextDisabled(const char* format,...){
 va_list args;va_start(args,format);va_list copy;va_copy(copy,args);
 char text[512];std::vsnprintf(text,sizeof(text),format,copy);va_end(copy);
 rendered_text.emplace_back(text);
 if(std::string(text).starts_with("Active: "))active_msaa_text=text;
 TextDisabledV(format,args);va_end(args);
}
bool ObservedCombo(const char* label,int* current,const char* items,int maximum=-1){
 WidgetHighlightProbe highlight(label);
 auto p=GetCursorScreenPos();float width=CalcItemWidth(),height=GetFrameHeight();
 bool observe=std::string(label)=="##fps"||std::string(label)=="##vsync"||std::string(label)=="##msaa"||std::string(label)=="##aniso"||std::string(label)=="##hd_ui"||std::string(label)=="##subtitles"||std::string(label)=="##cutscene_borders";
 // A combo popup ends ImGui logging when it closes its window. Use the real
 // rendered-text file sink so that EndCombo cannot clear the observed options.
 if(observe){std::ofstream("fps-widget.log",std::ios::trunc).close();LogToFile(-1,"fps-widget.log");}
 bool changed=Combo(label,current,items,maximum);
 if(observe){LogFinish();std::ifstream log("fps-widget.log");combo_text[label]={std::istreambuf_iterator<char>(log),{}};}
 field_bounds[label]={p.x,p.y,p.x+width,p.y+height};return changed;
}
bool ObservedBeginCombo(const char* label,const char* preview,ImGuiComboFlags flags=0){
 auto p=GetCursorScreenPos();float width=CalcItemWidth(),height=GetFrameHeight();
 field_bounds[label]={p.x,p.y,p.x+width,p.y+height};return BeginCombo(label,preview,flags);
}
bool ObservedSliderInt(const char* label,int* value,int minimum,int maximum,const char* format="%d",ImGuiSliderFlags flags=0){
 slider_formats[label]=format;slider_ranges[label]={minimum,maximum};
 bool changed=SliderInt(label,value,minimum,maximum,format,flags);auto a=GetItemRectMin(),b=GetItemRectMax();
 field_bounds[label]={a.x,a.y,b.x,b.y};return changed;
}
bool ObservedSliderFloat(const char* label,float* value,float minimum,float maximum,const char* format="%.3f",ImGuiSliderFlags flags=0){
 WidgetHighlightProbe highlight(label);return SliderFloat(label,value,minimum,maximum,format,flags);
}
bool ObservedCheckbox(const char* label,bool* value){
 bool changed=Checkbox(label,value);auto a=GetItemRectMin(),b=GetItemRectMax();
 field_bounds[label]={a.x,a.y,b.x,b.y};return changed;
}
bool ObservedButton(const char* label,const ImVec2& size=ImVec2(0,0)) {
 auto p=GetCursorScreenPos();float w=size.x<0?GetContentRegionAvail().x:size.x;
 bool result=Button(label,size);auto a=GetItemRectMin(),b=GetItemRectMax();
 button_centers[label]=size.y>0?ImVec2(p.x+w/2,p.y+size.y/2):ImVec2((a.x+b.x)/2,(a.y+b.y)/2);return result;
}
}
#define Button ObservedButton
#define SliderInt ObservedSliderInt
#define SliderFloat ObservedSliderFloat
#define EndChild ObservedEndChild
#define Checkbox ObservedCheckbox
#define Combo ObservedCombo
#define BeginCombo ObservedBeginCombo
#define TextDisabled ObservedTextDisabled
#define TextUnformatted ObservedTextUnformatted
#include "common/graphics.cpp"
#undef Button
#undef SliderInt
#undef SliderFloat
#undef EndChild
#undef Checkbox
#undef Combo
#undef BeginCombo
#undef TextDisabled
#undef TextUnformatted
#include "common/graphics_view.cpp"
// Network co-op only observes the Pause state here.
void darkwatch::coop::NotePaused(bool){}
#include <cstdlib>
#define CHECK(x) do { if (!(x)) {std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::exit(90);} } while(0)
static app::Settings actual;
static bool save_ok=true, active=true;
static unsigned saves=0, applies=0, displays=0, subtitle_calls=0;
static darkwatch::GraphicsRouteState route;
static uint8_t memory[1];
namespace app {
const GameInfo kGame{.settings="test-settings.toml"};
Settings& Get(){return actual;} Settings Snapshot(){return actual;}
Settings Normalize(Settings s){s.render_percent=std::clamp(s.render_percent,25u,200u);return s;}
void Apply(const Settings& s){actual=Normalize(s);++applies;}
bool Save(){++saves;return save_ok;} void ApplyDisplay(){++displays;}
Mode Desktop(){return {2560,1440};}
Mode RenderSize(const Settings& s){return {2560*s.render_percent/100,1440*s.render_percent/100};}
std::filesystem::path ExeDir(){return ".";}
}
namespace mem {uint8_t* Base(){return memory;}}
namespace gpu {static uint32_t effective_samples=1;uint32_t MsaaSamples(){return effective_samples;}}
namespace input {
static DeviceSnapshot device;
static ControllerFamily connected_family=ControllerFamily::Xbox;
DeviceSnapshot GetLastDevice(){return device;}
ControllerFamily GetControllerFamily(int port){return port==0?connected_family:ControllerFamily::Xbox;}
void SetActive(bool value){active=value;}
}
namespace darkwatch {
static ControlsSettings controls;
static uint32_t capture_result=0;
static bool capture_active=false;
static unsigned controls_applies=0,original_applies=0,configure_calls=0,preset_applies=0;
ControlsSettings ControlsDefaults(){ControlsSettings s;s.bindings[1].keys[0]='J';s.bindings[1].keys[1]='K';s.bindings[16].keys[0]='W';s.bindings[17].keys[0]='S';return s;}
ControlsSettings ControlsSnapshot(){return controls;}
bool ControlsApply(const ControlsSettings& s){controls=s;++controls_applies;return true;}
void ControlsBeginCapture(){capture_active=true;capture_result=0;}
void ControlsCancelCapture(){capture_active=false;capture_result=0;}
bool ControlsCapturing(){return capture_active;}
uint32_t ControlsTakeCapture(){auto result=capture_result;capture_result=0;return result;}
std::string ControlsKeyName(uint32_t key){return key==input::kMouseWheel?"Mouse Wheel":key?std::string(1,char(key)):"Unbound";}
GraphicsRouteState QueryGraphicsMenuRoute(const uint8_t*){return route;}
bool PauseMenuVisible(const uint8_t*){return route.paused;}
bool SetGraphicsSubtitles(uint8_t*,uint32_t expected,bool enabled){
 CHECK(expected==route.options);++subtitle_calls;route.subtitles=enabled;return true;
}
bool SetOriginalControls(uint8_t*,uint32_t expected,bool invert,bool vibration,int32_t sensitivity){
 CHECK(expected==route.options);++original_applies;route.invert=invert;route.vibration=vibration;route.sensitivity=sensitivity;return true;
}
bool SetControllerPreset(uint8_t*,uint32_t expected,int32_t preset){
 CHECK(expected==route.options);++preset_applies;if(preset<0||preset>4)return false;route.controller_preset=preset;return true;
}
bool OpenControllerConfiguration(uint8_t*,uint32_t expected){CHECK(expected==route.options);++configure_calls;route.route=GraphicsMenuRoute::Hidden;return true;}
static uint32_t native_pause_entry=0,native_pause_owner=0;
bool EnsureNativePauseEntries(uint8_t*){return route.paused&&route.route==GraphicsMenuRoute::OptionsMain;}
bool EnsureDesktopQuitEntry(uint8_t*){return false;}
uint32_t TakeNativePauseEntry(uint8_t*,uint32_t expected){
 auto entry=native_pause_entry;native_pause_entry=0;
 return route.paused&&route.route==GraphicsMenuRoute::Controls&&expected==native_pause_owner?entry:0;
}
}
static double fixture_fps=60;
static void Frame(float elapsed=1.f/60){
 rendered_text.clear();
 auto& io=ImGui::GetIO();io.DeltaTime=elapsed;io.DisplaySize={1280,720};
 ImGui::NewFrame();DarkwatchGraphicsUi(fixture_fps);ImGui::Render();
}
static void CheckNavigationOutline(const char* context){
 auto* parent=ImGui::FindWindowByName(g_controls?"Controls":"Graphics");CHECK(parent&&parent->DC.ChildWindows.Size);
 auto* child=parent->DC.ChildWindows[0];ImGui::SetScrollY(child,0);Frame();Frame();
 child_outline_vertices.clear();child_outline_indices.clear();widget_outline_vertices.clear();child_navigation_kept=true;
 const auto colors=GImGui->ColorStack.Size;const auto styles=GImGui->StyleVarStack.Size;
 probe_navigation=true;Frame();probe_navigation=false;
 CHECK(child_outline_vertices.count(child->Name)&&child_outline_indices.count(child->Name)&&widget_outline_vertices.count(child->Name));
 std::printf("navigation outline %s: child vertices=%d indices=%d widget ivory vertices=%d\n",context,
  child_outline_vertices[child->Name],child_outline_indices[child->Name],widget_outline_vertices[child->Name]);
 CHECK(child_outline_vertices[child->Name]==0&&child_outline_indices[child->Name]==0);
 CHECK(widget_outline_vertices[child->Name]>0&&child_navigation_kept);
 CHECK(GImGui->ColorStack.Size==colors&&GImGui->StyleVarStack.Size==styles);
 CHECK((ImGui::GetIO().ConfigFlags&(ImGuiConfigFlags_NavEnableKeyboard|ImGuiConfigFlags_NavEnableGamepad))==
  (ImGuiConfigFlags_NavEnableKeyboard|ImGuiConfigFlags_NavEnableGamepad));
}
static void Click(float x,float y){auto& io=ImGui::GetIO();io.AddMousePosEvent(x,y);Frame();
 io.AddMouseButtonEvent(0,true);Frame();io.AddMouseButtonEvent(0,false);Frame();}
static void ClickNamed(const char* name,bool scroll=false){
 CHECK(button_centers.count(name));auto p=button_centers[name];
 if(scroll){Frame();p=button_centers[name];auto* parent=ImGui::FindWindowByName(g_controls?"Controls":"Graphics");CHECK(parent&&parent->DC.ChildWindows.Size);
  auto* child=parent->DC.ChildWindows[0];
  ImGui::SetScrollY(child,child->Scroll.y+p.y-(child->InnerRect.Min.y+child->InnerRect.Max.y)/2);Frame();Frame();p=button_centers[name];}
 Click(p.x,p.y);
}
static void ClickField(const char* name,float fraction=.5f){
 CHECK(field_bounds.count(name));Frame();auto r=field_bounds[name];
 auto* parent=ImGui::FindWindowByName(g_controls?"Controls":"Graphics");CHECK(parent&&parent->DC.ChildWindows.Size);
 auto* child=parent->DC.ChildWindows[0];
 ImGui::SetScrollY(child,child->Scroll.y+(r.y+r.w)/2-(child->InnerRect.Min.y+child->InnerRect.Max.y)/2);
 Frame();Frame();r=field_bounds[name];CHECK(r.y>=child->InnerRect.Min.y&&r.w<=child->InnerRect.Max.y);
 Click(r.x+(r.z-r.x)*fraction,(r.y+r.w)/2);
}
static void SelectFps(bool enabled){
 CHECK(field_bounds.count("##fps")&&field_bounds["##fps"].z-field_bounds["##fps"].x>400);
 ClickField("##fps",.9f);Frame();
 CHECK(combo_text["##fps"].find("Off")!=std::string::npos&&combo_text["##fps"].find("On")!=std::string::npos);
 auto* popup=ImGui::FindWindowByName("##Combo_00");CHECK(popup&&popup->Active);
 auto point=popup->WorkRect.Min;
 Click(point.x+80,point.y+ImGui::GetTextLineHeight()/2+(enabled?ImGui::GetTextLineHeightWithSpacing():0));Frame();
 CHECK(g_view_draft.show_fps==enabled);
 CHECK(combo_text["##fps"].find(enabled?"On":"Off")!=std::string::npos);
 CHECK(!ImGui::IsPopupOpen(nullptr,ImGuiPopupFlags_AnyPopupId|ImGuiPopupFlags_AnyPopupLevel));
}
static void SelectQuality(const char* label,int index,const char* visible){
 CHECK(field_bounds.count(label)&&field_bounds[label].z-field_bounds[label].x>400);
 ClickField(label,.9f);Frame();
 if(std::string(label)!="##cap")CHECK(combo_text[label].find(visible)!=std::string::npos);
 auto* popup=ImGui::FindWindowByName("##Combo_00");CHECK(popup&&popup->Active);
 auto point=popup->WorkRect.Min;
 Click(point.x+80,point.y+ImGui::GetTextLineHeight()/2+index*ImGui::GetTextLineHeightWithSpacing());Frame();
 CHECK(!ImGui::IsPopupOpen(nullptr,ImGuiPopupFlags_AnyPopupId|ImGuiPopupFlags_AnyPopupLevel));
 if(std::string(label)!="##cap")CHECK(combo_text[label].find(visible)!=std::string::npos);
}
static input::Pad Poll(unsigned buttons=0,unsigned a=0,unsigned b=0){
 input::Pad p{};p.connected=true;p.buttons=uint16_t(buttons);p.analog[0]=uint8_t(a);p.analog[1]=uint8_t(b);
 DarkwatchGraphicsPad(0,p);return p;
}
int main(){
 ImGui::CreateContext();auto& io=ImGui::GetIO();io.IniFilename=nullptr;
 io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard|ImGuiConfigFlags_NavEnableGamepad;
 ImFontConfig config;config.SizePixels=22;g_body=io.Fonts->AddFontDefault(&config);g_title=g_body;
 unsigned char* pixels;int w,h;io.Fonts->GetTexDataAsRGBA32(&pixels,&w,&h);
 g_modes={{1280,720},{1920,1080},{2560,1440}};
 Frame();CHECK(!g_open&&ImGui::GetDrawData()->TotalVtxCount==0);
 // The counter is independent of every page/early return and uses the supplied host FPS.
 darkwatch::view::Apply({100,100,true});Frame();CHECK(!g_open&&ImGui::GetDrawData()->TotalVtxCount>0);
 auto fps_vertices=ImGui::GetForegroundDrawList()->VtxBuffer.Size;fixture_fps=144;Frame();
 CHECK(ImGui::GetForegroundDrawList()->VtxBuffer.Size>fps_vertices&&!io.WantCaptureMouse&&!io.WantCaptureKeyboard);
 for(auto& v:ImGui::GetForegroundDrawList()->VtxBuffer)CHECK(v.pos.x>1000&&v.pos.x<1280&&v.pos.y>0&&v.pos.y<70);
 darkwatch::view::Apply({});Frame();CHECK(ImGui::GetDrawData()->TotalVtxCount==0);fixture_fps=60;
 route={darkwatch::GraphicsMenuRoute::Visual,0x123400,0x123500,true,false};
 auto p=Poll(0,255);CHECK(p.connected&&!p.analog[0]&&!active&&!g_pad);Frame();
 CHECK(g_open&&ImGui::GetDrawData()->TotalVtxCount>100&&!io.MouseDrawCursor);
 Poll();Frame();CHECK(g_released);
 CheckNavigationOutline("main Graphics");
 // Actual slider input edits a draft; it must not resize live targets on every drag.
 ClickField("##internal",.75f);CHECK(g_draft.render_percent>100&&actual.render_percent==100&&applies==0);
 // New settings are ordinary draft controls in the same bounded scroll area.
 ClickField("##fov",.8f);CHECK(g_view_draft.fov_percent>100&&darkwatch::view::Snapshot().fov_percent==100);
 const auto world_fov=g_view_draft.fov_percent;
 ClickField("##weapon_fov",.8f);CHECK(g_view_draft.viewmodel_fov_percent>100&&darkwatch::view::Snapshot().viewmodel_fov_percent==100&&g_view_draft.fov_percent==world_fov);
 CHECK(slider_formats["##weapon_fov"]=="%d%%"&&slider_ranges["##weapon_fov"].first==50&&slider_ranges["##weapon_fov"].second==150);
 CHECK(std::find(rendered_text.begin(),rendered_text.end(),"WEAPON FOV")!=rendered_text.end());
 CHECK(std::find(rendered_text.begin(),rendered_text.end(),"Changes gun and hand framing.")!=rendered_text.end());
 CHECK(std::find(rendered_text.begin(),rendered_text.end(),"Level cutscenes only.")!=rendered_text.end());
 ClickField("##reticle",.8f);CHECK(g_view_draft.reticle_percent>100&&darkwatch::view::Snapshot().reticle_percent==100);
 SelectQuality("##cutscene_borders",0,"Off");CHECK(!g_view_draft.cutscene_borders&&darkwatch::view::Snapshot().cutscene_borders);
 SelectQuality("##cutscene_borders",1,"On");CHECK(g_view_draft.cutscene_borders);
 SelectQuality("##cutscene_borders",0,"Off");
 auto* graphics=ImGui::FindWindowByName("Graphics");CHECK(graphics&&graphics->DC.ChildWindows[0]->ScrollMax.y>0);
 CHECK(field_bounds["##fov"].w<field_bounds["##weapon_fov"].y&&field_bounds["##weapon_fov"].w<field_bounds["##reticle"].y&&field_bounds["##reticle"].w<field_bounds["##cutscene_borders"].y);
 CHECK(combo_text["##fps"].find("Off")!=std::string::npos);
 SelectFps(true);CHECK(g_view_draft.show_fps&&!darkwatch::view::Snapshot().show_fps);
 // Each quality control uses the actual Combo and mouse input; no live mutation before Apply.
 SelectQuality("##vsync",0,"Off");CHECK(!g_draft.vsync&&actual.vsync);
 SelectQuality("##cap",4,"144 FPS");CHECK(g_draft.fps_cap==144&&actual.fps_cap==60);
 SelectQuality("##cap",7,"Unlimited");CHECK(g_draft.fps_cap==0&&actual.fps_cap==60);
 SelectQuality("##cap",4,"144 FPS");CHECK(g_draft.fps_cap==144);
 SelectQuality("##msaa",1,"2x");CHECK(g_draft.msaa_samples==2&&actual.msaa_samples==1);
 SelectQuality("##msaa",2,"4x");CHECK(g_draft.msaa_samples==4&&actual.msaa_samples==1);
 SelectQuality("##msaa",0,"Off");CHECK(g_draft.msaa_samples==1);
 SelectQuality("##msaa",2,"4x");CHECK(g_draft.msaa_samples==4);
 gpu::effective_samples=2;Frame();CHECK(active_msaa_text.find("Active: 2x")!=std::string::npos&&g_draft.msaa_samples==4);
 gpu::effective_samples=1;Frame();CHECK(active_msaa_text.find("Active: Off")!=std::string::npos&&g_draft.msaa_samples==4);
 for(int i=0;i<6;++i){SelectQuality("##aniso",i,i?i==1?"1x":i==2?"2x":i==3?"4x":i==4?"8x":"16x":"Original");CHECK(g_draft.aniso==(i?1u<<(i-1):0)&&actual.aniso==0);}
 CHECK(g_view_draft.hd_ui&&darkwatch::view::Snapshot().hd_ui);
 SelectQuality("##hd_ui",0,"Off");CHECK(!g_view_draft.hd_ui&&darkwatch::view::Snapshot().hd_ui);
 SelectQuality("##hd_ui",1,"On");CHECK(g_view_draft.hd_ui);
 SelectQuality("##hd_ui",0,"Off");CHECK(!g_view_draft.hd_ui&&darkwatch::view::Snapshot().hd_ui);
 SelectFps(false);CHECK(!g_view_draft.show_fps&&!darkwatch::view::Snapshot().show_fps);
 SelectFps(true);CHECK(g_view_draft.show_fps&&!darkwatch::view::Snapshot().show_fps);
 ClickNamed("RESET VIEW DEFAULTS",true);CHECK(g_view_draft.fov_percent==100&&g_view_draft.reticle_percent==100&&g_view_draft.viewmodel_fov_percent==100&&g_view_draft.cutscene_borders&&g_view_draft.show_fps&&!g_view_draft.hd_ui&&applies==0);
 ClickField("##fov",.8f);ClickField("##reticle",.8f);ClickField("##weapon_fov",.8f);SelectQuality("##cutscene_borders",0,"Off");
 CHECK(button_centers["APPLY"].y>graphics->DC.ChildWindows[0]->InnerRect.Max.y&&button_centers["APPLY"].y<720);
 // Original subtitles remain on this page and use a guest-thread request on Apply.
 SelectQuality("##subtitles",1,"On");CHECK(g_subtitles_draft&&!route.subtitles);
 ClickNamed("APPLY");CHECK(saves==1&&actual.render_percent>100&&!g_confirm);
 CHECK(!actual.vsync&&actual.fps_cap==144&&actual.msaa_samples==4&&actual.aniso==16);
 Poll();CHECK(subtitle_calls==1&&route.subtitles);
 CHECK(darkwatch::view::Snapshot().fov_percent==g_view_draft.fov_percent&&darkwatch::view::Snapshot().reticle_percent==g_view_draft.reticle_percent&&darkwatch::view::Snapshot().show_fps&&!darkwatch::view::Snapshot().hd_ui);
 CHECK(darkwatch::view::Snapshot().viewmodel_fov_percent==g_view_draft.viewmodel_fov_percent&&!darkwatch::view::Snapshot().cutscene_borders);
 // Display confirmation is driven by real ImGui buttons, not direct helpers.
 // The Apply down/up must open confirmation without also activating Keep at
 // the same footer position on that release frame.
 g_draft.display_mode=app::DisplayMode::Windowed;g_draft.width=1920;g_draft.height=1080;
 auto apply_point=button_centers["APPLY"];io.AddMousePosEvent(apply_point.x,apply_point.y);Frame();
 io.AddMouseButtonEvent(0,true);Frame();CHECK(!g_confirm&&saves==1);
 io.AddMouseButtonEvent(0,false);Frame();CHECK(g_confirm&&displays==1&&saves==1);
 Frame();CHECK(g_confirm&&saves==1);
 ClickNamed("KEEP");CHECK(!g_confirm&&saves==2&&actual.display_mode==app::DisplayMode::Windowed);
 // Both explicit Revert and timeout restore the complete prior settings/view.
 auto retained=actual;auto retained_view=darkwatch::view::Snapshot();
 for(bool timeout:{false,true}){
  g_view_draft={50,50,false,true,50,true};g_draft.display_mode=app::DisplayMode::Fullscreen;g_draft.width=2560;g_draft.height=1440;
  g_draft.vsync=true;g_draft.fps_cap=30;g_draft.msaa_samples=1;g_draft.aniso=0;
  auto display_before=displays;ClickNamed("APPLY");CHECK(g_confirm&&displays==display_before+1&&saves==2);
  if(timeout)Frame(16);else ClickNamed("REVERT");
  CHECK(!g_confirm&&actual.display_mode==retained.display_mode&&actual.width==retained.width&&actual.height==retained.height&&displays==display_before+2&&saves==2);
  CHECK(actual.vsync==retained.vsync&&actual.fps_cap==retained.fps_cap&&actual.msaa_samples==retained.msaa_samples&&actual.aniso==retained.aniso);
  CHECK(darkwatch::view::Snapshot().fov_percent==retained_view.fov_percent&&darkwatch::view::Snapshot().reticle_percent==retained_view.reticle_percent&&darkwatch::view::Snapshot().show_fps==retained_view.show_fps&&darkwatch::view::Snapshot().hd_ui==retained_view.hd_ui);
  CHECK(darkwatch::view::Snapshot().viewmodel_fov_percent==retained_view.viewmodel_fov_percent&&darkwatch::view::Snapshot().cutscene_borders==retained_view.cutscene_borders);
 }
 save_ok=false;g_view_draft={130,80,false,true,75,false};g_draft.render_percent=125;g_draft.msaa_samples=2;g_draft.aniso=8;g_draft.vsync=true;g_draft.fps_cap=90;g_subtitles_draft=false;ApplyChanges();CHECK(saves==3&&std::strstr(g_notice,"Could not save"));
 CHECK(actual.msaa_samples==2&&actual.aniso==8&&actual.vsync&&actual.fps_cap==90);
 Poll();CHECK(!route.subtitles&&subtitle_calls==2);CHECK(darkwatch::view::Snapshot().fov_percent==130&&darkwatch::view::Snapshot().reticle_percent==80&&!darkwatch::view::Snapshot().show_fps&&darkwatch::view::Snapshot().hd_ui);
 CHECK(darkwatch::view::Snapshot().viewmodel_fov_percent==75&&!darkwatch::view::Snapshot().cutscene_borders);
 ClickField("##weapon_fov",.9f);SelectQuality("##cutscene_borders",1,"On");
 input::Pad stick{};stick.connected=true;stick.ly=20000;DarkwatchGraphicsPad(0,stick);CHECK(g_pad==1&&!stick.ly);
 Poll();Frame();
 // Back returns through the original B action; held physical input cannot back out twice.
 ClickNamed("BACK");CHECK(g_leave&&!g_open);p=Poll(0,0,255);CHECK(p.analog[1]==255);
 route.route=darkwatch::GraphicsMenuRoute::OptionsMain;p=Poll(0,0,255);CHECK(!p.analog[1]&&g_block_release);
 p=Poll();CHECK(!g_block_release);Frame();CHECK(!io.MouseDrawCursor);
 // Opening a fresh page does not inherit a pending confirmation or old subtitle value.
 route.route=darkwatch::GraphicsMenuRoute::Visual;route.subtitles=false;Poll();Frame();CHECK(g_open&&!g_subtitles_draft);
 CHECK(g_view_draft.viewmodel_fov_percent==75&&!g_view_draft.cutscene_borders);
 g_draft.width=1280;g_draft.height=720;ApplyChanges();CHECK(g_confirm);route.route=darkwatch::GraphicsMenuRoute::Hidden;
 Poll();Frame();CHECK(!g_confirm&&!g_open);
 // Actual Controls widgets preserve 20 physical actions and one weapon-switch row.
 darkwatch::controls=darkwatch::ControlsDefaults();save_ok=true;
 route={};route.route=darkwatch::GraphicsMenuRoute::Controls;route.options=0x123400;route.page=0x123600;
 route.controls_available=true;route.vibration=true;route.sensitivity=5;route.sensitivity_min=1;route.sensitivity_max=10;route.controller_preset=0;
 Poll();Frame();CHECK(g_open&&g_controls&&!g_confirm&&g_controls_draft.bindings[16].keys[0]=='W');
 CheckNavigationOutline("main Controls");
 // Labels follow the actual original preset; Lefty maps the left stick to looking.
 CHECK(!std::strcmp(ActionName(8),"INTERACT")&&!std::strcmp(ActionName(7),"SIGHT MODE"));
 CHECK(!std::strcmp(ActionName(0),"D-PAD UP")&&!std::strcmp(ActionName(1),"SWITCH WEAPONS"));
 constexpr const char* face[][4]={{"INTERACT","RELOAD","MELEE","JUMP"},{"JUMP","MELEE","RELOAD","SWITCH WEAPONS"},
  {"INTERACT","MELEE","RELOAD","THROW"},{"INTERACT","MELEE","RELOAD","THROW"},{"INTERACT","JUMP","THROW","RELOAD"}};
 for(int preset=0;preset<5;++preset){g_original_draft.controller_preset=preset;
  for(unsigned action=8;action<12;++action)CHECK(!std::strcmp(ActionName(action),face[preset][action-8]));
  CHECK(!std::strcmp(ActionName(16),preset==2?"LOOK UP":"MOVE FORWARD"));
  CHECK(std::strlen(ActionDescription(16))>10);
  auto cycle=preset==1?11u:1u;
  CHECK(!std::strcmp(ActionName(cycle),"SWITCH WEAPONS"));
  CHECK(!std::strcmp(ActionDescription(cycle),"Swap between your carried weapons."));
  Frame();CHECK(std::count(rendered_text.begin(),rendered_text.end(),"SWITCH WEAPONS")==1);
  CHECK(std::find(rendered_text.begin(),rendered_text.end(),ActionDescription(cycle))!=rendered_text.end());}
 g_original_draft.controller_preset=2;CHECK(!std::strcmp(ActionName(6),"SIGHT MODE")&&!std::strcmp(ActionName(7),"CROUCH"));
 g_original_draft.controller_preset=-1;CHECK(!std::strcmp(ActionName(16),"LEFT STICK UP")&&!std::strcmp(ActionName(8),"A BUTTON"));
 CHECK(!std::strcmp(ActionName(1),"D-PAD DOWN"));
 Frame();CHECK(std::find(rendered_text.begin(),rendered_text.end(),"SWITCH WEAPONS")==rendered_text.end());
 CHECK(button_centers["J"].y==button_centers["K"].y&&button_centers["J"].x<button_centers["K"].x);
 // Chieftain's cycle action is Y, so both binding widgets must address physical slot 11.
 g_original_draft.controller_preset=1;g_controls_draft.bindings[11].keys[0]='N';g_controls_draft.bindings[11].keys[1]='O';Frame();
 ClickNamed("N",true);CHECK(g_capture_action==11&&g_capture_slot==0);
 darkwatch::capture_result='P';darkwatch::capture_active=false;Frame();
 ClickNamed("O",true);CHECK(g_capture_action==11&&g_capture_slot==1);
 darkwatch::capture_result=input::kMouseWheel;darkwatch::capture_active=false;Frame();
 CHECK(g_controls_draft.bindings[11].keys[0]=='P'&&g_controls_draft.bindings[11].keys[1]==input::kMouseWheel);
 CHECK(button_centers.count("Mouse Wheel")&&button_centers["P"].y==button_centers["Mouse Wheel"].y);
 CHECK(g_controls_draft.bindings[1].keys[0]=='J'&&g_controls_draft.bindings[1].keys[1]=='K');
 g_controls_draft.bindings[11]={};
 g_original_draft.controller_preset=0;Frame();
 CHECK(button_centers["J"].y==button_centers["K"].y&&button_centers["J"].x<button_centers["K"].x);
 CHECK(button_centers.count("W")&&button_centers.count("S")&&ImGui::GetDrawData()->TotalVtxCount>100);
 // A keyboard primary and wheel alternate edit the same saved physical binding pair.
 ClickNamed("J",true);CHECK(darkwatch::capture_active&&g_capture_action==1&&g_capture_slot==0);
 CHECK(std::strstr(g_notice,"scroll the wheel"));
 darkwatch::capture_result='L';darkwatch::capture_active=false;Frame();
 CHECK(g_controls_draft.bindings[1].keys[0]=='L'&&g_controls_draft.bindings[1].keys[1]=='K');
 ClickNamed("K",true);CHECK(darkwatch::capture_active&&g_capture_action==1&&g_capture_slot==1);
 darkwatch::capture_result=input::kMouseWheel;darkwatch::capture_active=false;Frame();
 CHECK(g_controls_draft.bindings[1].keys[0]=='L'&&g_controls_draft.bindings[1].keys[1]==input::kMouseWheel);
 CHECK(darkwatch::controls.bindings[1].keys[0]=='J'&&darkwatch::controls.bindings[1].keys[1]=='K');
 // Wheel conflicts name the existing action; Cancel preserves it, Replace moves it.
 ClickNamed("W",true);darkwatch::capture_result=input::kMouseWheel;darkwatch::capture_active=false;Frame();Frame();
 CHECK(g_conflict_action==1);
 CHECK(std::find(rendered_text.begin(),rendered_text.end(),"Mouse Wheel is assigned to SWITCH WEAPONS. Replace that assignment?")!=rendered_text.end());
 ClickNamed("CANCEL");CHECK(g_controls_draft.bindings[16].keys[0]=='W'&&g_controls_draft.bindings[1].keys[1]==input::kMouseWheel);
 ClickNamed("W",true);darkwatch::capture_result=input::kMouseWheel;darkwatch::capture_active=false;Frame();Frame();
 ClickNamed("REPLACE");CHECK(g_controls_draft.bindings[16].keys[0]==input::kMouseWheel&&!g_controls_draft.bindings[1].keys[1]);
 ClickNamed("Mouse Wheel",true);darkwatch::capture_result='W';darkwatch::capture_active=false;Frame();
 // Primary/alternate remain aliases: reusing a key on the same action moves it without a conflict.
 ClickNamed("L",true);darkwatch::capture_result=input::kMouseWheel;darkwatch::capture_active=false;Frame();
 CHECK(g_conflict_action<0&&g_controls_draft.bindings[1].keys[0]==input::kMouseWheel&&!g_controls_draft.bindings[1].keys[1]);
 g_controls_draft.bindings[1].keys[1]='K';Frame();
 ClickNamed("K",true);darkwatch::capture_result=input::kMouseWheel;darkwatch::capture_active=false;Frame();
 CHECK(g_conflict_action<0&&!g_controls_draft.bindings[1].keys[0]&&g_controls_draft.bindings[1].keys[1]==input::kMouseWheel);
 ClickNamed("Mouse Wheel",true);darkwatch::capture_result=darkwatch::kCaptureClear;darkwatch::capture_active=false;Frame();
 CHECK(!g_controls_draft.bindings[1].keys[0]&&!g_controls_draft.bindings[1].keys[1]);
 ClickNamed("RESET DEFAULTS");CHECK(g_controls_draft.bindings[1].keys[0]=='J'&&g_controls_draft.bindings[1].keys[1]=='K');
 ClickNamed("J",true);darkwatch::capture_result='L';darkwatch::capture_active=false;Frame();
 ClickNamed("K",true);darkwatch::capture_result=input::kMouseWheel;darkwatch::capture_active=false;Frame();
 ClickNamed("APPLY");Poll();CHECK(darkwatch::controls.bindings[1].keys[0]=='L'&&darkwatch::controls.bindings[1].keys[1]==input::kMouseWheel);
 // Back discards an unapplied change; reopening reads the last applied keyboard/wheel pair.
 ClickNamed("L",true);darkwatch::capture_result='J';darkwatch::capture_active=false;Frame();ClickNamed("BACK");Poll();
 route.route=darkwatch::GraphicsMenuRoute::OptionsMain;Poll();Poll();Frame();
 route.route=darkwatch::GraphicsMenuRoute::Controls;Poll();Frame();
 CHECK(g_controls_draft.bindings[1].keys[0]=='L'&&g_controls_draft.bindings[1].keys[1]==input::kMouseWheel);
 auto controls_before=darkwatch::controls_applies,original_before=darkwatch::original_applies;
 // Click an actual binding button; capture completion only edits the draft.
 ClickNamed("W",true);CHECK(darkwatch::capture_active&&g_capture_action==16&&g_capture_slot==0);
 ClickNamed("APPLY");CHECK(darkwatch::controls_applies==controls_before&&darkwatch::capture_active&&g_capture_action==16);
 darkwatch::capture_result='Z';darkwatch::capture_active=false;Frame();
 CHECK(g_controls_draft.bindings[16].keys[0]=='Z'&&darkwatch::controls.bindings[16].keys[0]=='W');
 // Conflict is explicit and Cancel leaves both actions untouched.
 ClickNamed("Z",true);darkwatch::capture_result='S';darkwatch::capture_active=false;Frame();Frame();
 CHECK(g_conflict_action==17&&g_controls_draft.bindings[16].keys[0]=='Z');
 ClickNamed("CANCEL");CHECK(g_conflict_action<0&&g_controls_draft.bindings[17].keys[0]=='S');
 ClickNamed("Z",true);darkwatch::capture_result='S';darkwatch::capture_active=false;Frame();Frame();
 ClickNamed("REPLACE");CHECK(g_controls_draft.bindings[16].keys[0]=='S'&&!g_controls_draft.bindings[17].keys[0]);
 // Reserved input keeps a visible capture active for retry; Escape cancels only capture.
 ClickNamed("S",true);darkwatch::capture_result=darkwatch::kCaptureReserved;Frame();
 CHECK(darkwatch::capture_active&&g_capture_action==16&&std::strstr(g_notice,"reserved"));
 darkwatch::capture_result=darkwatch::kCaptureCancelled;darkwatch::capture_active=false;
 io.AddKeyEvent(ImGuiKey_Escape,true);Frame();CHECK(g_open&&!g_leave&&g_capture_action<0);
 io.AddKeyEvent(ImGuiKey_Escape,false);Frame();
 ClickNamed("S",true);darkwatch::capture_result=darkwatch::kCaptureClear;darkwatch::capture_active=false;Frame();
 CHECK(!g_controls_draft.bindings[16].keys[0]);
 ClickNamed("RESET DEFAULTS");CHECK(g_controls_draft.bindings[16].keys[0]=='W'&&darkwatch::controls_applies==controls_before);
 g_original_draft.invert=true;g_original_draft.sensitivity=7;g_controls_draft.mouse_millidegrees=75;
 ClickNamed("APPLY");CHECK(darkwatch::controls_applies==controls_before+1&&darkwatch::controls.mouse_millidegrees==75);
 CHECK(darkwatch::original_applies==original_before);Poll();CHECK(darkwatch::original_applies==original_before+1&&route.invert&&route.sensitivity==7);
 // Host save failure still queues original profile changes and preserves live PC settings.
 save_ok=false;g_original_draft.vibration=false;ApplyControls();Poll();CHECK(!route.vibration&&std::strstr(g_notice,"Could not save"));save_ok=true;
 // Controller layout uses the original action; returning retains unapplied PC draft.
 g_controls_draft.mouse_millidegrees=99;g_original_draft.invert=false;g_original_draft.vibration=true;g_original_draft.sensitivity=3;
 ClickNamed("CONTROLLER LAYOUT...",true);CHECK(g_configuring);
 Poll();CHECK(darkwatch::configure_calls==1);Poll();Frame();CHECK(!g_open&&!g_visual);
 route.route=darkwatch::GraphicsMenuRoute::Controls;route.controller_preset=2;Poll();Frame();CHECK(g_open&&g_controls_draft.mouse_millidegrees==99);
 CHECK(!g_original_draft.invert&&g_original_draft.vibration&&g_original_draft.sensitivity==3);
 CHECK(g_original_draft.controller_preset==2&&!std::strcmp(ActionName(16),"LOOK UP"));
 ClickNamed("BACK");CHECK(g_leave&&!g_open);Poll();route.route=darkwatch::GraphicsMenuRoute::OptionsMain;Poll();Frame();
 route.route=darkwatch::GraphicsMenuRoute::Controls;Poll();Frame();CHECK(g_controls_draft.mouse_millidegrees==75);
 // Direct page/owner changes need no hidden render frame to cancel an outstanding capture.
 ClickNamed("W",true);CHECK(darkwatch::capture_active&&g_capture_action==16);
 route.route=darkwatch::GraphicsMenuRoute::Visual;Poll();Frame();
 CHECK(g_open&&!g_controls&&!darkwatch::capture_active&&g_capture_action<0&&g_conflict_action<0);
 route.route=darkwatch::GraphicsMenuRoute::Controls;Poll();Frame();ClickNamed("W",true);
 route.options+=0x100;Poll();Frame();CHECK(!darkwatch::capture_active&&g_capture_action<0);
 // Conflicts are page-owned, so asynchronous route/owner changes cannot leave a modal behind.
 ClickNamed("W",true);darkwatch::capture_result='S';darkwatch::capture_active=false;Frame();Frame();
 CHECK(g_conflict_action==17);route.options+=0x100;Poll();Frame();CHECK(g_conflict_action<0&&g_capture_action<0);
 auto untouched=g_controls_draft.bindings;ReplaceBinding();CHECK(!std::memcmp(&g_controls_draft.bindings,&untouched,sizeof(untouched)));
 CHECK(!ImGui::IsPopupOpen(nullptr,ImGuiPopupFlags_AnyPopupId|ImGuiPopupFlags_AnyPopupLevel));
 // Capturing Mouse1 over the footer cannot also accept the newly appearing conflict.
 g_controls_draft.bindings[15].keys[0]=1;
 ClickNamed("W",true);CHECK(g_capture_action==16);
 auto point=button_centers["APPLY"];io.AddMousePosEvent(point.x,point.y);
 darkwatch::capture_result=1;darkwatch::capture_active=false;
 io.AddMouseButtonEvent(0,true);Frame();CHECK(g_conflict_action==15);
 io.AddMouseButtonEvent(0,false);Frame();CHECK(g_conflict_action==15);
 CHECK(g_controls_draft.bindings[16].keys[0]=='W'&&g_controls_draft.bindings[15].keys[0]==1);
 ClickNamed("REPLACE");CHECK(g_conflict_action<0&&g_controls_draft.bindings[16].keys[0]==1&&!g_controls_draft.bindings[15].keys[0]);
 // A stale Escape event on the result frame also cannot choose the new confirmation.
 g_controls_draft.bindings[16].keys[0]='W';g_controls_draft.bindings[15].keys[0]=1;Frame();
 ClickNamed("W",true);darkwatch::capture_result=1;darkwatch::capture_active=false;
 io.AddKeyEvent(ImGuiKey_Escape,true);Frame();CHECK(g_conflict_action==15);
 io.AddKeyEvent(ImGuiKey_Escape,false);Frame();CHECK(g_conflict_action==15);
 ClickNamed("CANCEL");CHECK(g_conflict_action<0&&g_controls_draft.bindings[16].keys[0]=='W');
 // Pause Options uses the original Controls route and exposes Graphics without losing the draft.
 route.paused=true;Poll();Frame();g_controls_draft.mouse_millidegrees=88;
 CHECK(button_centers.count("GRAPHICS")&&button_centers.count("CONTROLS"));
 ClickNamed("GRAPHICS");Frame();CHECK(g_page_graphics&&DarkwatchGraphicsVisible()&&!g_leave);
 ClickField("##fov",.7f);ClickField("##reticle",.6f);ClickField("##weapon_fov",.9f);SelectQuality("##cutscene_borders",1,"On");SelectFps(true);CHECK(g_view_draft.fov_percent>100&&g_view_draft.show_fps);
 const auto paused_view=g_view_draft;const auto paused_graphics=g_draft;
 ClickNamed("CONTROLS");Frame();CHECK(!g_page_graphics&&!g_leave&&g_controls_draft.mouse_millidegrees==88);
 ClickNamed("GRAPHICS");Frame();CHECK(g_page_graphics&&g_view_draft.fov_percent==paused_view.fov_percent&&g_view_draft.reticle_percent==paused_view.reticle_percent&&g_view_draft.show_fps==paused_view.show_fps&&g_view_draft.hd_ui==paused_view.hd_ui&&g_draft.msaa_samples==paused_graphics.msaa_samples);
 CHECK(g_view_draft.viewmodel_fov_percent==paused_view.viewmodel_fov_percent&&g_view_draft.cutscene_borders==paused_view.cutscene_borders);
 auto hd_displays=displays;auto hd_before=g_view_draft;
 SelectQuality("##hd_ui",0,"Off");ApplyChanges();CHECK(!g_confirm&&displays==hd_displays&&!darkwatch::view::Snapshot().hd_ui);
 SelectQuality("##hd_ui",1,"On");ApplyChanges();CHECK(!g_confirm&&displays==hd_displays&&darkwatch::view::Snapshot().hd_ui);
 CHECK(darkwatch::view::Snapshot().fov_percent==hd_before.fov_percent&&darkwatch::view::Snapshot().reticle_percent==hd_before.reticle_percent&&darkwatch::view::Snapshot().show_fps==hd_before.show_fps);
 auto original_subtitles=subtitle_calls;g_subtitles_draft=true;ApplyChanges();Poll();CHECK(subtitle_calls==original_subtitles);
 io.AddMouseButtonEvent(1,true);Frame();CHECK(!g_page_graphics&&!g_leave&&g_controls_draft.mouse_millidegrees==88);
 io.AddMouseButtonEvent(1,false);Frame();
 // Right Mouse during capture binds instead of backing out; its result frame stays isolated.
 ClickNamed("W",true);darkwatch::capture_result=2;darkwatch::capture_active=false;
 io.AddMouseButtonEvent(1,true);Frame();CHECK(g_open&&!g_leave&&g_controls_draft.bindings[16].keys[0]==2);
 io.AddMouseButtonEvent(1,false);Frame();
 io.AddMouseButtonEvent(1,true);Frame();CHECK(g_leave&&!g_open);
 // Pause itself has no host side panel; the native menu opens its owned page.
 route={};route.route=darkwatch::GraphicsMenuRoute::OptionsMain;route.paused=true;
 route.pause_settings_available=true;route.options=0x225500;route.page=0x226600;
 Poll();Poll();Frame();Frame();CHECK(!g_open&&!DarkwatchGraphicsVisible());
 CHECK(!ImGui::FindWindowByName("Pause settings"));
 darkwatch::native_pause_owner=route.options;darkwatch::native_pause_entry=1;
 button_centers.clear();
 route.route=darkwatch::GraphicsMenuRoute::Controls;Poll();Frame();
 CHECK(g_open&&g_controls&&g_page_graphics&&g_from_pause);
 CHECK(!button_centers.count("GRAPHICS")&&!button_centers.count("CONTROLS"));
 CheckNavigationOutline("pause Graphics");
 const auto pause_saved=darkwatch::view::Snapshot();
 ClickField("##weapon_fov",.25f);SelectQuality("##cutscene_borders",0,"Off");
 CHECK(g_view_draft.viewmodel_fov_percent<100&&!g_view_draft.cutscene_borders&&darkwatch::view::Snapshot().viewmodel_fov_percent==pause_saved.viewmodel_fov_percent&&darkwatch::view::Snapshot().cutscene_borders==pause_saved.cutscene_borders);
 auto pause_displays=displays;ClickNamed("APPLY");CHECK(!g_confirm&&displays==pause_displays);
 CHECK(darkwatch::view::Snapshot().viewmodel_fov_percent==g_view_draft.viewmodel_fov_percent&&!darkwatch::view::Snapshot().cutscene_borders);
 const auto pause_applied=darkwatch::view::Snapshot();
 ClickField("##weapon_fov",.9f);SelectQuality("##cutscene_borders",1,"On");
 // A direct Pause entry returns straight through the original B page pop.
 ClickNamed("BACK");CHECK(g_leave);p=Poll();CHECK(p.analog[1]==255);
 CHECK(darkwatch::view::Snapshot().viewmodel_fov_percent==pause_applied.viewmodel_fov_percent&&!darkwatch::view::Snapshot().cutscene_borders);
 route.route=darkwatch::GraphicsMenuRoute::OptionsMain;Poll();Poll();Frame();Frame();
 CHECK(!g_leave&&!g_open);
 button_centers.clear();darkwatch::native_pause_entry=2;route.route=darkwatch::GraphicsMenuRoute::Controls;Poll();Frame();
 CHECK(g_open&&g_controls&&!g_page_graphics&&g_from_pause);
 CHECK(!button_centers.count("GRAPHICS")&&!button_centers.count("CONTROLS"));
 CheckNavigationOutline("pause Controls");
 // Native Pause uses the same single weapon row and wheel capture path.
 route.controller_preset=0;g_original_draft.controller_preset=0;Frame();
 CHECK(std::count(rendered_text.begin(),rendered_text.end(),"SWITCH WEAPONS")==1);
 ClickNamed("K",true);CHECK(g_capture_action==1&&g_capture_slot==1);
 darkwatch::capture_result=input::kMouseWheel;darkwatch::capture_active=false;Frame();ClickNamed("APPLY");
 CHECK(darkwatch::controls.bindings[1].keys[0]=='J'&&darkwatch::controls.bindings[1].keys[1]==input::kMouseWheel);
 ClickNamed("BACK");p=Poll(0,0,255);CHECK(p.analog[1]==255);
 route.route=darkwatch::GraphicsMenuRoute::OptionsMain;p=Poll(0,0,255);CHECK(!p.analog[1]&&g_block_release);
 Poll();Frame();Frame();CHECK(!g_block_release&&!g_leave);
 // A foreign owner cannot select the Graphics tab or direct-pause return.
 darkwatch::native_pause_entry=1;route.options+=4;route.route=darkwatch::GraphicsMenuRoute::Controls;
 Poll();Frame();CHECK(g_open&&!g_page_graphics&&!g_from_pause);
 ImGui::DestroyContext();std::puts("actual ImGui Graphics + Controls: pause Graphics link, contextual right-click Back/capture isolation, slider/subtitles, real Apply/Keep/Revert clicks and timeout/save failure, single switch-weapons row, keyboard/wheel primary and alternate across five presets and both menu contexts, 20-action rebind/capture/conflict/cancel/clear/defaults, original settings/layout roundtrip passed");
}
'''

CONTROLLER_COVERAGE = r'''
 // Family layouts use the themed host page and the same unapplied Controls draft.
 io.AddMouseButtonEvent(1,false);Frame();
 for(bool paused:{false,true}) for(auto family:{input::ControllerFamily::PlayStation,input::ControllerFamily::Switch}) {
  route.route=darkwatch::GraphicsMenuRoute::Hidden;Poll();Poll();Frame();Frame();
  route={};route.route=darkwatch::GraphicsMenuRoute::Controls;route.options=paused?0x411100:0x422200;
  route.page=route.options+0x100;route.paused=paused;route.controls_available=true;route.controller_preset=0;
  route.sensitivity_min=1;route.sensitivity_max=10;route.sensitivity=5;
  if(paused){darkwatch::native_pause_owner=route.options;darkwatch::native_pause_entry=2;}
  input::device={1,true,family};Poll();Poll();Frame();Frame();CHECK(g_open&&!g_page_graphics&&g_from_pause==paused);
  g_controls_draft.mouse_millidegrees=143;g_original_draft.invert=true;g_original_draft.sensitivity=8;
  const auto kept_bindings=g_controls_draft.bindings;
  const auto configured=darkwatch::configure_calls,applied=darkwatch::controls_applies,saved=saves,presets=darkwatch::preset_applies;
  for(unsigned exit=0;exit<4;++exit){
   input::connected_family=family;input::device={1,exit%2==0,exit%2==0?family:input::ControllerFamily::Xbox};
   ClickNamed("CONTROLLER LAYOUT...",true);Poll();Frame();Frame();
   CHECK(g_controller_layout&&!g_configuring&&g_open&&!g_leave&&g_layout_family==family);
   CHECK(darkwatch::configure_calls==configured&&darkwatch::controls_applies==applied&&saves==saved);
   CHECK(button_centers.count("BACK")&&field_bounds.count("##controller preset"));
   CHECK(std::find(rendered_text.begin(),rendered_text.end(),family==input::ControllerFamily::PlayStation?"PLAYSTATION CONTROLLER":"SWITCH CONTROLLER")!=rendered_text.end());
   CHECK(std::count(rendered_text.begin(),rendered_text.end(),"LOOK / AIM")==1);
   CHECK(std::count(rendered_text.begin(),rendered_text.end(),"MOVE")==1);
   for(unsigned button=0;button<16;++button)CHECK(std::find(rendered_text.begin(),rendered_text.end(),ActionName(button))!=rendered_text.end());
   auto* layout=ImGui::FindWindowByName("Controls")->DC.ChildWindows[0];CHECK(layout->ScrollMax.y>0);
   // Use the actual preset selector; it must change only the draft before Apply.
   auto bounds=field_bounds["##controller preset"];Click(bounds.z-10,(bounds.y+bounds.w)/2);Frame();
   auto* popup=ImGui::FindWindowByName("##Combo_00");CHECK(popup&&popup->Active);
   const auto top=popup->WorkRect.Min;const float line=bounds.w-bounds.y-2*ImGui::GetStyle().FramePadding.y;
   Click(top.x+30,top.y+line/2+2*(line+ImGui::GetStyle().ItemSpacing.y));Frame();
   CHECK(g_original_draft.controller_preset==2&&route.controller_preset==0&&darkwatch::preset_applies==presets);
   // Switching to the mouse on this page keeps the chosen controller illustration.
   input::device={2,false,input::ControllerFamily::Xbox};Frame();CHECK(g_layout_family==family);
   if(exit==0)ClickNamed("BACK");
   if(exit==1){io.AddKeyEvent(ImGuiKey_Escape,true);Frame();io.AddKeyEvent(ImGuiKey_Escape,false);Frame();}
   if(exit==2){io.AddMouseButtonEvent(1,true);Frame();Frame();Frame();io.AddMouseButtonEvent(1,false);Frame();}
   if(exit==3){Poll(0,0,255);Frame();Frame();Frame();Poll();Frame();Frame();}
   CHECK(!g_controller_layout&&g_open&&!g_leave&&!g_configuring);
   CHECK(g_controls_draft.mouse_millidegrees==143&&g_original_draft.invert&&g_original_draft.sensitivity==8);
   CHECK(!std::memcmp(&g_controls_draft.bindings,&kept_bindings,sizeof(kept_bindings)));
   CHECK(g_original_draft.controller_preset==2&&darkwatch::configure_calls==configured&&darkwatch::controls_applies==applied&&saves==saved);
  }
  ClickNamed("APPLY");CHECK(darkwatch::controls_applies==applied+1&&route.controller_preset==0);
  Poll();CHECK(darkwatch::preset_applies==presets+1&&route.controller_preset==2);
  // PC Reset Defaults does not silently reset the separately chosen controller layout.
  ClickNamed("RESET DEFAULTS");CHECK(g_original_draft.controller_preset==2&&route.controller_preset==2);
  CHECK(darkwatch::controls_applies==applied+1&&darkwatch::preset_applies==presets+1);
  // Holding the activating face button must not activate the new page again.
  auto* host=ImGui::FindWindowByName("Controls");auto* scroll=host->DC.ChildWindows[0];
  auto p=button_centers["CONTROLLER LAYOUT..."];
  ImGui::SetScrollY(scroll,scroll->Scroll.y+p.y-(scroll->InnerRect.Min.y+scroll->InnerRect.Max.y)/2);Frame();Frame();
  io.AddMousePosEvent(-100,-100);Frame();
  ImGui::FocusWindow(scroll);ImGui::SetFocusID(scroll->GetID("CONTROLLER LAYOUT..."),scroll);GImGui->NavDisableHighlight=false;
  input::device={3,true,family};Poll(0,255);Frame();Frame();
  CHECK(g_controller_layout&&!g_leave&&!g_configuring);
  for(unsigned held=0;held<4;++held){Poll(0,255);Frame();CHECK(g_controller_layout&&!g_leave);}
  Poll();Frame();Frame();CHECK(!ImGui::IsPopupOpen(nullptr,ImGuiPopupFlags_AnyPopupId|ImGuiPopupFlags_AnyPopupLevel));
  Poll(0,0,255);Frame();Frame();CHECK(!g_controller_layout&&g_open&&!g_leave);
  Poll();Frame();Frame();
  input::device={3,true,family};ClickNamed("CONTROLLER LAYOUT...",true);Frame();CHECK(g_controller_layout);
  route.options+=0x1000;Poll();Frame();CHECK(!g_controller_layout&&g_open);
 }
 input::device={};input::connected_family=input::ControllerFamily::Xbox;
'''


class GraphicsUiTests(unittest.TestCase):
    def run_fixture(self, fixture):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler, "clang++ required")
        with tempfile.TemporaryDirectory(prefix="graphics-ui-", dir=ROOT / "build") as temp:
            folder = Path(temp)
            source, exe = folder / "test.cpp", folder / "test.exe"
            source.write_text(fixture)
            command = [compiler, "-std=c++20", "-O1", "-fuse-ld=lld", "-I", str(SDK),
                       "-I", str(ROOT / "xbexbe/src"), "-I", str(ROOT / "build/xbexbe/_deps/tomlplusplus-src/include"), "-I", str(IMGUI), str(source)]
            command += [str(IMGUI / name) for name in ("imgui.cpp", "imgui_draw.cpp", "imgui_tables.cpp", "imgui_widgets.cpp")]
            built = subprocess.run(command + ["-o", str(exe), "-luser32"], capture_output=True, text=True, timeout=90)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(exe)], cwd=folder, capture_output=True, text=True, timeout=15)
            print(ran.stdout.strip())
            return ran

    def test_real_imgui_page_and_input_lifetime(self):
        ran = self.run_fixture(FIXTURE.replace('ImGui::DestroyContext();std::puts(',
                                              CONTROLLER_COVERAGE + 'ImGui::DestroyContext();std::puts('))
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)



if __name__ == "__main__":
    unittest.main()
