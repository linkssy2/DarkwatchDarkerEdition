#include "versus_menu.h"
#include "character_selection.h"
#include "character_runtime.h"
#include "character_preview.h"
#include "graphics_view.h"
#include "settings_skin.h"
#include "language.h"
#include "native_menu.h"
#include "app/app.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include <array>
#include <algorithm>
#include <atomic>
#include <cstring>
#include <mutex>
#include <string>
#include <imgui_internal.h>

namespace {
using darkwatch::settings::Character;
struct State {
    uint32_t page = 0;
    std::array<Character, 4> choices{};
    std::array<bool, 4> joined{}, ready{}, connected{};
    std::array<std::string, 4> names{"Player 1", "Player 2", "Player 3", "Player 4"};
    std::array<bool, 4> editing{};
    bool active = false, failed = false;
};
struct Request {
    uint32_t page = 0; int step = 0; bool accept = false, back = false;
    unsigned edit = 0; std::string name;
};
std::mutex mutex;
State published, draft;
// Names are temporary match identities, retained until this process exits.
auto session_names = State{}.names;
struct NameEditor { uint32_t page = 0; bool active = false, focus = false; unsigned key = 0, selection = 3; std::array<char,17> text{}; };
std::array<NameEditor,4> editors{}; // Render-thread state; guest changes travel through requests.
std::array<Request, 4> requests{};
std::array<std::atomic<unsigned>, 4> pressed{};
std::array<unsigned, 4> held{};
std::array<std::atomic<bool>, 4> released{};
std::array<bool, 4> block_release{};
std::array<std::atomic<bool>, 4> connected{};
std::atomic<uint32_t> visible{0};

bool Span(const uint8_t* base, uint64_t at, uint64_t bytes) {
    if (!base || !at || !bytes || at + bytes > (uint64_t(1) << 32)) return false;
    for (auto p = at & ~(uint64_t(mem::kPage)-1); p < at + bytes; p += mem::kPage)
        if (!mem::IsCommitted(uint32_t(p))) return false;
    return true;
}
template<class T> bool Read(const uint8_t* base, uint64_t at, T& out) {
    if (!Span(base, at, sizeof(out))) return false;
    std::memcpy(&out, base + at, sizeof(out)); return true;
}
bool Page(const uint8_t* base, uint32_t page) {
    uint32_t type = 0, ref = 0; uint8_t online = 1;
    constexpr char name[] = "multiplayer_profile_select";
    return Span(base, page, 0x268) && Read(base, page, type) && type == 0x42A6D8 &&
        Read(base, uint64_t(page)+0x30, ref) && Span(base, uint64_t(ref)+2, sizeof(name)) &&
        !std::memcmp(base+uint64_t(ref)+2, name, sizeof(name)) &&
        Read(base, uint64_t(page)+0x250, online) && online == 0;
}
State Query(const uint8_t* base) {
    State result; uint32_t frontend = 0, depth = 0, top = 0;
    if (base != kernel::g_base || !(DarkwatchCharacterContentReady() || DarkwatchOriginalContentReady()) ||
        !Read(base, 0x4AD664, frontend) || !Read(base, uint64_t(frontend)+8, depth) || !depth || depth > 20) return result;
    for (unsigned i = 1; i <= depth; ++i) {
        if (!Read(base, uint64_t(frontend)+8+i*4, top)) return {};
        if (Page(base, top)) result.page = top;
    }
    if (!result.page) return result;
    for (unsigned p = 0; p < 4; ++p) {
        uint8_t joined = 0;
        if (!Read(base, uint64_t(result.page)+0xD0+0x7C*p, joined) || joined > 1) return {};
        result.joined[p] = joined; result.connected[p] = connected[p].load();
    }
    if (top != result.page) return result;
    uint32_t manager = 0, list = 0; uint16_t count = 0;
    if (!Read(base, 0x4AD314, manager) || !Read(base, uint64_t(manager)+8, count) || count > 512 ||
        !Read(base, uint64_t(manager)+12, list) || !Span(base, list, count*4ull)) return result;
    for (unsigned i = count; i; --i) {
        uint32_t root = 0, kind = 0; uint8_t shown = 0, focused = 0;
        if (!Read(base, uint64_t(list)+(i-1)*4, root) || !root ||
            !Read(base, uint64_t(root)+0x3C, kind) || !Read(base, uint64_t(root)+0x2F, shown) ||
            !Read(base, uint64_t(root)+0x2E, focused)) return result;
        if (root == result.page) { result.active = shown && focused; return result; }
        if (shown && kind == 3) return result;
    }
    return result;
}
bool NativeReady(uint8_t* base) {
    const auto* thread = kernel::Current();
    return thread && thread->ctx && thread->ctx->esp >= 0x2000 &&
        Span(base, uint64_t(thread->ctx->esp)-0x2000, 0x2000);
}
bool Native(uint8_t* base, uint32_t page, unsigned port, uint32_t callback) {
    if (!NativeReady(base)) return false;
    const auto* thread = kernel::Current();
    auto call = *thread->ctx; call.ecx = page;
    kernel::CallGuest(call, callback, {port});
    DarkwatchInvalidateMenuSnapshot(); return true;
}
bool NameCharacter(unsigned c) {
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
        (c >= '0' && c <= '9') || c == ' ' || c == '-' || c == '\'';
}
bool ValidName(const std::string& name) {
    return !name.empty() && name.size() <= 16 && name.front() != ' ' && name.back() != ' ' &&
        std::all_of(name.begin(),name.end(),[](unsigned char c){return NameCharacter(c);});
}
bool Rename(uint8_t* base, uint32_t page, unsigned port, const std::string& value) {
    uint8_t joined = 0;
    if (port >= 4 || !ValidName(value) || !Page(base,page) || !NativeReady(base) ||
        !Read(base,uint64_t(page)+0xD0+0x7C*port,joined) || joined != 1) return false;
    auto call = *kernel::Current()->ctx;
    const uint32_t name = call.esp-0x100, text = name+16, profile = page+0x64+0x7C*port;
    call.esp = name-0x20;
    std::memcpy(base+text,value.c_str(),value.size()+1);
    call.ecx = name; kernel::CallGuest(call,0x138FA,{text});
    // Profile's first field is its owned name; preserve the rest of this temporary profile.
    call.ecx = profile; kernel::CallGuest(call,0x129DF,{name});
    call.ecx = name; kernel::CallGuest(call,0x11C1A,{});
    uint32_t handle = 0;
    return Read(base,profile,handle) && Span(base,uint64_t(handle)+2,value.size()+1) &&
        !std::memcmp(base+uint64_t(handle)+2,value.c_str(),value.size()+1);
}
bool Join(uint8_t* base, uint32_t page, unsigned port) {
    if (port >= 4 || !Page(base, page) || !NativeReady(base)) return false;
    uint8_t joined = 0;
    if (!Read(base, uint64_t(page)+0xD0+0x7C*port, joined) || joined > 1) return false;
    if (joined) return true;
    auto call = *kernel::Current()->ctx;
    const uint32_t profile = call.esp-0x180, name = profile+0x70, text = profile+0x80;
    call.esp = profile-0x20;
    std::memset(base+profile, 0, 0x100);
    if (!ValidName(draft.names[port])) return false;
    std::strcpy(reinterpret_cast<char*>(base+text), draft.names[port].c_str());
    // Use the native profile constructor, owned copy and destructor; never write saved profiles.
    call.ecx = profile; kernel::CallGuest(call, 0xCAAEF, {});
    call.ecx = name; kernel::CallGuest(call, 0x138FA, {text});
    call.ecx = profile; kernel::CallGuest(call, 0xCAA7B, {name});
    call.ecx = name; kernel::CallGuest(call, 0x11C1A, {});
    call.ecx = page; kernel::CallGuest(call, 0xEB218, {port, profile});
    call.ecx = profile; kernel::CallGuest(call, 0xCAA17, {});
    DarkwatchInvalidateMenuSnapshot();
    return Read(base, uint64_t(page)+0xD0+0x7C*port, joined) && joined == 1;
}
void Publish(State state) {
    const auto old = visible.exchange(state.active ? state.page : 0);
    if (old != visible.load()) {
        for (auto& value : pressed) value = 0;
        held = {}; for (auto& value : released) value = false;
        if (old) block_release.fill(true);
    }
    std::lock_guard guard(mutex); published = state;
}
void Refresh(uint8_t* base, bool actions) {
    auto state = Query(base);
    if (state.page != draft.page) {
        draft = {}; draft.page = state.page;
        draft.choices = darkwatch::settings::versus_characters();
        if (!DarkwatchCharacterContentReady()) draft.choices.fill(Character::Trooper);
        draft.names = session_names;
    }
    for (unsigned p = 0; p < 4; ++p)
        if (!state.joined[p] || !state.connected[p]) {
            draft.ready[p] = false;
            if (!state.connected[p]) draft.editing[p] = false;
        }
    std::array<Request, 4> work{};
    if (actions) { std::lock_guard guard(mutex); work = requests; requests = {}; }
    for (unsigned p = 0; p < 4; ++p) {
        const auto& request = work[p];
        if (!request.page || !state.active || request.page != state.page || !state.connected[p]) continue;
        if (request.edit) {
            if (!draft.ready[p]) {
                if (request.edit == 1) draft.editing[p] = true;
                else if (request.edit == 3) draft.editing[p] = false;
                else if (request.edit == 2 && draft.editing[p]) {
                    if (ValidName(request.name) && Join(base,state.page,p) && Rename(base,state.page,p,request.name)) {
                        draft.names[p] = session_names[p] = request.name;
                        draft.editing[p] = false; draft.failed = false;
                    } else draft.failed = true;
                }
            }
            state = Query(base); continue;
        }
        if (draft.editing[p]) continue;
        if (request.back) {
            if (draft.ready[p]) draft.ready[p] = false;
            else if (!Native(base, state.page, p, 0xEB52F)) draft.failed = true;
        } else if (request.step && !draft.ready[p]) {
            if (!Join(base, state.page, p)) { draft.failed = true; continue; }
            const int count = int(darkwatch::settings::kCharacterCount);
            draft.choices[p] = DarkwatchCharacterContentReady()
                ? Character((int(draft.choices[p]) + (request.step < 0 ? count-1 : 1)) % count) : Character::Trooper;
        } else if (request.accept) {
            if (!state.joined[p]) {
                if (!Join(base, state.page, p)) draft.failed = true;
            } else {
                draft.ready[p] = !draft.ready[p];
                bool all = true;
                for (unsigned n = 0; n < 4; ++n)
                    if (draft.editing[n] || (state.joined[n] && (!state.connected[n] || !draft.ready[n]))) all = false;
                if (all && draft.ready[p]) {
                    const auto previous = darkwatch::settings::versus_characters();
                    const bool changed = previous != draft.choices;
                    bool saved = NativeReady(base) && darkwatch::settings::set_versus_characters(draft.choices);
                    if (saved && changed) saved = app::Save();
                    if (!saved || !Native(base, state.page, p, 0xEB887)) {
                        darkwatch::settings::set_versus_characters(previous);
                        draft.ready[p] = false; draft.failed = true;
                    }
                }
            }
        }
        state = Query(base);
    }
    state.choices = draft.choices; state.ready = draft.ready; state.failed = draft.failed;
    state.names = draft.names; state.editing = draft.editing;
    Publish(state);
}
}

void DarkwatchVersusRefresh(uint8_t* base) { Refresh(base, false); }
bool DarkwatchVersusVisible() { return visible.load() != 0; }
bool DarkwatchHideVersusContent(uint32_t page) {
    // Native roots still draw while unfocused or fading after they leave the stack.
    return (DarkwatchCharacterContentReady() || DarkwatchOriginalContentReady()) && Page(kernel::g_base, page);
}
bool DarkwatchVersusPad(int port, input::Pad& pad) {
    if (port < 0 || port >= 4) return false;
    connected[port] = pad.connected;
    if (port == 0) Refresh(kernel::g_base, true);
    const unsigned keys = (pad.buttons & 15) | (pad.analog[0] > 30 || (pad.buttons & (1u<<4)) ? 16 : 0) |
        (pad.analog[1] > 30 ? 32 : 0) | (pad.analog[2] > 30 ? 64 : 0) | (pad.analog[3] > 30 ? 128 : 0) |
        (pad.lx < -16000 ? 4 : 0) | (pad.lx > 16000 ? 8 : 0) |
        (pad.ly > 16000 ? 1 : 0) | (pad.ly < -16000 ? 2 : 0);
    if (!DarkwatchVersusVisible()) {
        if (!block_release[port]) return false;
        if (!keys) block_release[port] = false;
    } else {
        if (!keys) released[port] = true;
        if (released[port]) pressed[port].fetch_or(keys & ~held[port]);
        held[port] = keys;
    }
    const bool present = pad.connected; pad = {}; pad.connected = present;
    input::SetActive(false); return true;
}

void DarkwatchVersusDraw() {
    State state; { std::lock_guard guard(mutex); state = published; }
    if (!state.active) return;
    auto& io = ImGui::GetIO(); const auto size=io.DisplaySize;
    if(size.x<=0||size.y<=0)return;
    ImGui::SetNextWindowPos({0,0}); ImGui::SetNextWindowSize(size);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, {0,0});
    ImGui::Begin("Versus Characters", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove |
        ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoBackground | ImGuiWindowFlags_NoScrollWithMouse);
    auto* draw=ImGui::GetWindowDrawList();
    const auto fonts=darkwatch::skin::Select(darkwatch::view::Snapshot().hd_ui);
    auto* font=fonts.body?fonts.body:ImGui::GetFont();
    const float ui=std::min(size.x/1000.f,size.y/600.f);
    auto text=[&](const char* label,float x,float y,float height,float width,ImU32 color=IM_COL32(238,225,203,255)){
        label=darkwatch::language::Text(label);auto extent=font->CalcTextSizeA(height,10000,0,label);
        if(extent.x>width){height*=width/extent.x;extent=font->CalcTextSizeA(height,10000,0,label);}
        draw->AddText(font,height,{x-extent.x/2,y},color,label);
    };
    auto button=[&](const char* label,ImVec2 pos,ImVec2 extent,bool enabled,float font_size,bool selected=false){
        ImGui::SetCursorPos(pos);ImGui::BeginDisabled(!enabled);
        const bool clicked=ImGui::InvisibleButton(label,extent);
        darkwatch::skin::Row(draw,pos,{pos.x+extent.x,pos.y+extent.y},enabled&&(selected||ImGui::IsItemHovered()));
        text(label,pos.x+extent.x/2,pos.y+(extent.y-font_size)/2,font_size,extent.x-10*ui,
             enabled?IM_COL32(238,225,203,255):IM_COL32(125,125,125,255));
        ImGui::EndDisabled();return clicked;
    };
    draw->AddRectFilled({0,0},size,IM_COL32(8,7,6,225));
    text("VERSUS",size.x/2,7*ui,26*ui,size.x-20*ui);
    const ImVec2 origin{8*ui,42*ui}, area{size.x-16*ui,size.y-120*ui};
    constexpr const char* labels[]{"PLAYER ONE","PLAYER TWO","PLAYER THREE","PLAYER FOUR"};
    for(unsigned p=0;p<4;++p){
        ImGui::PushID(int(p));Request request{state.page};unsigned keys=pressed[p].exchange(0);
        const bool editable=state.connected[p];
        if (!p && io.WantTextInput) keys = 0;
        if(!p&&editable&&released[p]&&!state.editing[p]&&!io.WantTextInput){
            if(ImGui::IsKeyPressed(ImGuiKey_UpArrow,false))keys|=1;
            if(ImGui::IsKeyPressed(ImGuiKey_DownArrow,false))keys|=2;
            if(ImGui::IsKeyPressed(ImGuiKey_LeftArrow,false))keys|=4;
            if(ImGui::IsKeyPressed(ImGuiKey_RightArrow,false))keys|=8;
            if(ImGui::IsKeyPressed(ImGuiKey_Enter,false)||ImGui::IsKeyPressed(ImGuiKey_Space,false))keys|=16;
            if(ImGui::IsKeyPressed(ImGuiKey_Escape,false))keys|=32;
            if(ImGui::IsKeyPressed(ImGuiKey_F2,false)){keys|=128;editors[p].focus=true;}
        }
        const bool change=editable&&!state.ready[p];
        auto& navigation=editors[p];
        if(navigation.page!=state.page){navigation={};navigation.page=state.page;}
        if (!state.editing[p]) {
            auto& selected=navigation.selection;
            if(!change&&selected<3)selected=3;
            if(editable&&(keys&1))selected=selected==4?3:selected==3?(change?1:4):selected==0?4:0;
            if(editable&&(keys&2))selected=selected==0?1:selected<3?3:selected==3?4:(change?0:3);
            if(change&&(keys&12)){
                if(selected==1||selected==2)selected=(keys&4)?1:2;
                else request.step=(keys&4)?-1:1;
            }
            if(editable&&(keys&16)){
                if(selected==0)request.edit=1;
                else if(selected<3)request.step=selected==1?-1:1;
                else if(selected==3)request.accept=true;
                else request.back=true;
            }
            if(editable&&(keys&32))request.back=true;
            if(change&&(keys&128))request.edit=1;
        }
        {
            // A controller port keeps its own box regardless of other players joining.
            const std::array<float,4> rect{(p%2)*.5f,(p/2)*.5f,.5f,.5f};
            const ImVec2 a{origin.x+area.x*rect[0]+4*ui,origin.y+area.y*rect[1]+4*ui};
            const ImVec2 b{a.x+area.x*rect[2]-8*ui,a.y+area.y*rect[3]-8*ui};
            draw->AddRectFilled(a,b,IM_COL32(15,13,12,245));
            draw->AddRect(a,b,IM_COL32(136,107,64,255),0,0,ui);
            const float scale=std::min((b.x-a.x)/500.f,(b.y-a.y)/250.f);
            const ImVec2 pos{(a.x+b.x-500*scale)/2,(a.y+b.y-250*scale)/2};
            auto at=[&](float x,float y){return ImVec2{pos.x+x*scale,pos.y+y*scale};};
            darkwatch::skin::Row(draw,at(12,8),at(488,40),false);
            text(labels[p],pos.x+250*scale,pos.y+12*scale,21*scale,450*scale);
            auto& editor=editors[p];
            if (!state.editing[p]) editor.active=false;
            if (state.editing[p]) {
                if (!editor.active || editor.page!=state.page) {
                    editor.active=true;editor.page=state.page;editor.key=0;
                    std::strcpy(editor.text.data(),state.names[p].c_str());
                }
                ImGui::SetCursorPos(at(20,48));ImGui::SetNextItemWidth(460*scale);
                ImGui::PushFont(font);ImGui::SetWindowFontScale(20*scale/font->FontSize);
                if(editor.focus){ImGui::SetKeyboardFocusHere();editor.focus=false;}
                const bool enter=ImGui::InputText("##player_name",editor.text.data(),editor.text.size(),
                    ImGuiInputTextFlags_EnterReturnsTrue|ImGuiInputTextFlags_AutoSelectAll|ImGuiInputTextFlags_CallbackCharFilter,
                    [](ImGuiInputTextCallbackData* data){return NameCharacter(data->EventChar)?0:1;});
                const bool typing=ImGui::IsItemActive();
                const auto text_id=ImGui::GetItemID();
                ImGui::SetWindowFontScale(1);ImGui::PopFont();
                if(typing&&!p)keys=0;
                if(keys&1)editor.key=editor.key>=40?(editor.key==40?30:35):editor.key<10?40+(editor.key>=5):editor.key-10;
                if(keys&2)editor.key=editor.key>=40?(editor.key==40?0:5):editor.key>=30?40+(editor.key%10>=5):editor.key+10;
                if(keys&4)editor.key=editor.key>=40?81-editor.key:(editor.key+39)%40;
                if(keys&8)editor.key=editor.key>=40?81-editor.key:(editor.key+1)%40;
                auto detach=[&](){if(ImGui::GetActiveID()==text_id)ImGui::ClearActiveID();};
                auto erase=[&](){detach();const auto n=std::strlen(editor.text.data());if(n)editor.text[n-1]=0;};
                auto add=[&](unsigned key){
                    constexpr char alphabet[]="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -'";
                    const auto n=std::strlen(editor.text.data());
                    if(key==39)erase();else if(n<16){detach();editor.text[n]=alphabet[key];editor.text[n+1]=0;}
                };
                if(keys&64)erase();
                if((keys&16)&&editor.key<40)add(editor.key);
                constexpr char alphabet[]="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -'";
                for(unsigned key=0;key<40;++key){
                    ImGui::PushID(int(key));const char letter[]{key<39?alphabet[key]:'\0',0};
                    const auto cell=at(20+(key%10)*46,92+(key/10)*26);
                    if(button(key==39?"DEL":key==36?"SPACE":letter,cell,{44*scale,24*scale},editable,12*scale))add(key);
                    if(key==editor.key)draw->AddRect(cell,{cell.x+44*scale,cell.y+24*scale},IM_COL32(238,225,203,255));
                    ImGui::PopID();
                }
                std::string name=editor.text.data();
                const auto first=name.find_first_not_of(' '),last=name.find_last_not_of(' ');
                name=first==std::string::npos?std::string{}:name.substr(first,last-first+1);
                const bool done=button("DONE",at(20,208),{224*scale,30*scale},editable&&ValidName(name),16*scale,editor.key==40);
                const bool cancel=button("CANCEL",at(254,208),{226*scale,30*scale},editable,16*scale,editor.key==41);
                if((done||enter||(keys&128)||((keys&16)&&editor.key==40))&&ValidName(name)){request.edit=2;request.name=name;}
                if(cancel||((keys&16)&&editor.key==41)||(keys&32)||(typing&&ImGui::IsKeyPressed(ImGuiKey_Escape,false)))request.edit=3;
            } else {
            darkwatch::preview::Draw(state.choices[p],at(15,48),at(200,238),ImGui::GetTime(),darkwatch::view::Snapshot().hd_textures);
            const auto caption=std::string(darkwatch::language::Text("NAME"))+": "+state.names[p];
            if(button(caption.c_str(),at(210,48),{270*scale,30*scale},change,17*scale,editor.selection==0)){request.edit=1;editor.focus=true;}
            text(darkwatch::settings::CharacterName(state.choices[p]),pos.x+345*scale,pos.y+83*scale,15*scale,270*scale);
            if(button("PREVIOUS",at(210,102),{130*scale,34*scale},change,16*scale,editor.selection==1))request.step=-1;
            if(button("NEXT",at(350,102),{130*scale,34*scale},change,16*scale,editor.selection==2))request.step=1;
            if(button(!editable?"CONNECT CONTROLLER":!state.joined[p]?"SELECT":state.ready[p]?"CANCEL READY":"READY",at(210,148),{270*scale,36*scale},editable,18*scale,editor.selection==3))request.accept=true;
            if(editable){if(button("BACK",at(210,198),{270*scale,34*scale},true,16*scale,editor.selection==4))request.back=true;}
            }
        }
        if(request.step||request.accept||request.back||request.edit){std::lock_guard guard(mutex);requests[p]=request;}
        ImGui::PopID();
    }
    const bool editing=std::any_of(state.editing.begin(),state.editing.end(),[](bool v){return v;});
    text(editing?"A: SELECT    X: DELETE    Y: DONE    B: CANCEL":"Choose your character, then Ready. Y or F2: edit name.",size.x/2,size.y-58*ui,17*ui,size.x-24*ui);
    text(state.failed?"Could not save settings. Try again.":"UP, DOWN: MOVE    A, ENTER: SELECT    B, ESC: BACK",
         size.x/2,size.y-22*ui,13*ui,size.x-24*ui);
    ImGui::End();ImGui::PopStyleVar();
}
