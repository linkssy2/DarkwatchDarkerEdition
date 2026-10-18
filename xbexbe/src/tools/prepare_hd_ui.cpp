#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include "common/hd_ui_assets.h"
#include "common/hd_ui_filter.h"
#include "common/hd_ui_font.h"
#include "common/hd_ui_hud_masks.h"
#include "hd_ui_png.h"
#include <toml++/toml.hpp>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <optional>
#include <vector>

namespace {
struct Region { darkwatch::hd::PngOverride image; std::array<uint32_t,4> dest; };
struct Override { std::optional<darkwatch::hd::PngOverride> image; std::vector<Region> regions; bool original_alpha=false; };
std::array<uint32_t,4> Rectangle(const toml::node_view<const toml::node>& node) {
    const auto* values=node.as_array();
    if(!values || values->size()!=4)throw std::runtime_error("PNG rectangle needs four integers");
    std::array<uint32_t,4> result{};
    for(unsigned i=0;i<4;++i){auto v=(*values)[i].value<int64_t>();if(!v||*v<0||*v>UINT32_MAX)throw std::runtime_error("PNG rectangle integer");result[i]=uint32_t(*v);}
    return result;
}
bool HudCell(uint32_t offset,const std::array<uint32_t,4>& dest) {
    // Exact nonoverlapping cells from the original HUD info. The overflowing
    // EvilBlood cell and the authored red Damage field are deliberately excluded.
    constexpr std::array<uint32_t,4> cells[]{
        {3,0,141,41},{151,7,74,10},{152,17,74,10},{13,177,8,33},
        {1,175,9,40},{195,85,60,107},{2,107,191,13},{0,42,127,62}};
    return offset==103041076 && std::find(std::begin(cells),std::end(cells),dest)!=std::end(cells);
}
bool OriginalPanelAlpha(uint32_t offset) {
    constexpr uint32_t panels[]{101214580,102130036,100516340,102557300,102754292,100319220};
    return std::find(std::begin(panels),std::end(panels),offset)!=std::end(panels);
}
std::vector<std::optional<Override>> Overrides(const std::filesystem::path& directory) {
    using namespace darkwatch;
    std::vector<std::optional<Override>> result(std::size(hd::kAssets));
    if(directory.empty() || !std::filesystem::exists(directory/"overrides.toml"))return result;
    const auto table=toml::parse_file((directory/"overrides.toml").string());
    if(table["version"].value<int64_t>()!=1)throw std::runtime_error("PNG override manifest version");
    const auto* entries=table["texture"].as_array();
    if(!entries){if(table.contains("texture"))throw std::runtime_error("PNG override texture list");return result;}
    if(entries->size()>std::size(hd::kAssets))throw std::runtime_error("Too many PNG overrides");
    for(const auto& value:*entries){
        const auto* item=value.as_table();if(!item)throw std::runtime_error("PNG override entry type");
        const auto offset=(*item)["native_offset"].value<int64_t>();
        const auto name=(*item)["name"].value<std::string>();
        if(!offset||*offset<0||*offset>UINT32_MAX||!name)
            throw std::runtime_error("PNG override requires exact name and native_offset");
        size_t found=std::size(hd::kAssets);
        for(size_t i=0;i<std::size(hd::kAssets);++i)if(hd::kAssets[i].offset==*offset&&*name==hd::kAssets[i].name){found=i;break;}
        if(found==std::size(hd::kAssets)||result[found])throw std::runtime_error("Unknown or duplicate PNG original texture identity");
        const auto& a=hd::kAssets[found];
        auto image=[&](const toml::table& table){
            auto file=table["file"].value<std::string>();
            if(!file)throw std::runtime_error("PNG override requires file");
            auto fit=table["fit"].value<std::string>();
            if((table.contains("fit")&&!fit)||(fit&&*fit!="exact"&&*fit!="contain"))throw std::runtime_error("PNG fit must be exact or contain");
            return hd::PngOverride{a.offset,a.name,std::filesystem::u8path(*file),Rectangle(table["crop"]),fit=="contain"};
        };
        Override entry;
        if(const auto* regions=(*item)["region"].as_array()){
            if(item->contains("file")||item->contains("crop")||item->contains("fit")||item->contains("alpha")||regions->empty()||regions->size()>8)
                throw std::runtime_error("PNG region list or mixed full/partial override");
            for(const auto& value:*regions){
                const auto* table=value.as_table();if(!table||table->contains("alpha"))throw std::runtime_error("PNG region entry or unsupported alpha policy");
                Region region{image(*table),Rectangle((*table)["dest"])};const auto& d=region.dest;
                if(!d[2]||!d[3]||uint64_t(d[0])+d[2]>a.width||uint64_t(d[1])+d[3]>a.height||!HudCell(a.offset,d))
                    throw std::runtime_error("PNG region is not a supported original HUD cell");
                for(const auto& previous:entry.regions){const auto& p=previous.dest;
                    if(d[0]<p[0]+p[2]&&p[0]<d[0]+d[2]&&d[1]<p[1]+p[3]&&p[1]<d[1]+d[3])
                        throw std::runtime_error("Overlapping PNG regions");}
                entry.regions.push_back(std::move(region));
            }
        }else{
            if(item->contains("region"))throw std::runtime_error("PNG region must be an array");
            entry.image=image(*item);
            if(item->contains("alpha")){
                const auto alpha=(*item)["alpha"].value<std::string>();
                if(alpha!="original"||!OriginalPanelAlpha(a.offset))throw std::runtime_error("Original alpha is restricted to the six authored menu panels");
                entry.original_alpha=true;
            }
        }
        result[found]=std::move(entry);
    }
    return result;
}
}

int main(int argc, char** argv) {
    using namespace darkwatch;
    try {
        if (argc != 3 && argc != 4) throw std::runtime_error("usage: prepare_hd_ui original-packfile output-pack [restored-art-directory]");
        const std::filesystem::path art = argc==4 ? std::filesystem::path(argv[3]) : std::filesystem::path{};
        const auto overrides=Overrides(art);
        const HRESULT com=CoInitializeEx(nullptr,COINIT_MULTITHREADED);
        struct ComScope{bool active;~ComScope(){if(active)CoUninitialize();}} com_scope{SUCCEEDED(com)};
        Microsoft::WRL::ComPtr<IWICImagingFactory> imaging;
        if(SUCCEEDED(com))CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&imaging));
        std::ifstream source(argv[1], std::ios::binary);
        if (!source) throw std::runtime_error("Original packfile could not be opened");
        const std::filesystem::path output(argv[2]), temporary = output.string() + ".tmp";
        std::ofstream file(temporary, std::ios::binary | std::ios::trunc);
        if (!file) throw std::runtime_error("HD output could not be opened");
        hd::PackHeader header{{'D','W','H','D','U','0','0','2'}, 2, uint32_t(std::size(hd::kAssets)), 0};
        std::vector<hd::PackEntry> entries(header.count);
        uint32_t restored=0,partial=0,fonts=0,originals=0;
        file.write(reinterpret_cast<const char*>(&header), sizeof(header));
        file.write(reinterpret_cast<const char*>(entries.data()), entries.size() * sizeof(entries[0]));
        for (size_t i = 0; i < entries.size(); ++i) {
            const auto& a = hd::kAssets[i];
            std::vector<uint8_t> native(a.bytes), pixels;
            source.seekg(a.offset);
            if (!source.read(reinterpret_cast<char*>(native.data()), native.size()) || hd::Hash(native) != a.native_hash)
                throw std::runtime_error(std::string("Original texture identity mismatch: ") + a.name);
            std::span<const uint8_t> palette(native.data() + 92, a.palette_bytes);
            std::span<const uint8_t> payload(native.data() + 92 + a.palette_bytes, a.payload_bytes);
            std::vector<uint8_t> large;
            auto decode=[&](){if(pixels.empty()&&!hd_ui::DecodeNative(a.width,a.height,a.format==11?0:a.format,payload,palette,pixels))
                throw std::runtime_error(std::string("Native texture decode failed: ")+a.name);};
            if(overrides[i]&&overrides[i]->image){
                std::string reason;
                if(hd::ReadPng(imaging.Get(),art,*overrides[i]->image,a.width*4,a.height*4,large,reason)){
                    if(overrides[i]->original_alpha){
                        decode();const auto original=hd_ui::Upscale4x(a.width,a.height,pixels);
                        if(original.size()!=large.size())throw std::runtime_error("Original panel alpha extent");
                        for(size_t p=0;p<large.size();p+=4){
                            if(!original[p+3])large[p]=large[p+1]=large[p+2]=0;
                            else if(!large[p+3])std::copy_n(original.data()+p,3,large.data()+p);
                            large[p+3]=original[p+3];
                        }
                        std::cout<<"Restored "<<a.name<<" with original material opacity/backing.\n";
                    }
                    ++restored;
                }
                else std::cerr<<"Original retained for "<<a.name<<" ("<<a.offset<<"): "<<reason<<'\n';
            }else if(overrides[i]){
                uint32_t replaced=0;
                for(const auto& region:overrides[i]->regions){
                    std::string reason;std::vector<uint8_t> cell;const auto& d=region.dest;
                    if(!hd::ReadPng(imaging.Get(),art,region.image,d[2]*4,d[3]*4,cell,reason)){
                        std::cerr<<"Original cell retained for "<<a.name<<" ["<<d[0]<<','<<d[1]<<"]: "<<reason<<'\n';continue;}
                    if(large.empty()){decode();large=hd_ui::Upscale4x(a.width,a.height,pixels);if(large.size()!=hd::PixelBytes(a))throw std::runtime_error("Partial atlas baseline failed");}
                    for(uint32_t y=0;y<d[3]*4;++y)std::copy_n(cell.data()+size_t(y)*d[2]*16,d[2]*16,
                        large.data()+(size_t(d[1]*4+y)*a.width*4+d[0]*4)*4);
                    ++replaced;
                }
                if(replaced){++partial;std::cout<<"Partially restored "<<a.name<<": "<<replaced<<" approved cells; other cells retain original artwork.\n";}
            }else if(a.offset==103115060u){
                decode();if(hd_ui::ReconstructHudMasks(a,pixels,large)){
                    ++partial;std::cout<<"Partially reconstructed "<<a.name<<": 32 pinned monochrome cells; other masks retain original artwork.\n";
                }
            }else if(hd_ui::FindFontCells(a.offset)){
                decode();if(hd_ui::ReconstructFont(a,pixels,large))++fonts;
            }else if(const uint32_t core_offset=hd_ui::FontCoreForGlow(a.offset)){
                for(const auto& core:hd::kAssets)if(core.offset==core_offset){
                    std::vector<uint8_t> core_native(core.bytes),regular;
                    source.seekg(core.offset);
                    if(!source.read(reinterpret_cast<char*>(core_native.data()),core_native.size())||hd::Hash(core_native)!=core.native_hash)
                        throw std::runtime_error("Original font core identity mismatch");
                    if(!hd_ui::DecodeNative(core.width,core.height,core.format==11?0:core.format,
                        {core_native.data()+92+core.palette_bytes,core.payload_bytes},
                        {core_native.data()+92,core.palette_bytes},regular))throw std::runtime_error("Original font core decode failed");
                    decode();if(hd_ui::ReconstructFontGlow(a,pixels,regular,large))++fonts;
                    break;
                }
            }
            if(!large.empty() && large.size()!=hd::PixelBytes(a))throw std::runtime_error("Restored dimensions mismatch");
            auto& e = entries[i];
            e.native_offset = uint64_t(file.tellp());
            file.write(reinterpret_cast<const char*>(native.data()), native.size());
            if(!large.empty()){
                e.pixels_offset = uint64_t(file.tellp()); e.pixels_hash = hd::Hash(large);
                file.write(reinterpret_cast<const char*>(large.data()), large.size());
            }else ++originals;
            if (!file) throw std::runtime_error("HD asset write failed");
        }
        header.bytes = uint64_t(file.tellp());
        file.seekp(0); file.write(reinterpret_cast<const char*>(&header), sizeof(header));
        file.write(reinterpret_cast<const char*>(entries.data()), entries.size() * sizeof(entries[0]));
        file.close();
        if (!file) throw std::runtime_error("HD asset finalization failed");
        // MoveFileEx atomically replaces the cache only after every original identity passes.
        if (!MoveFileExW(temporary.c_str(), output.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
            throw std::runtime_error("HD asset replacement failed");
        std::cout << "Prepared " << entries.size() << " pinned identities: "<<restored<<" restored PNGs, "<<fonts
                  <<" reconstructed font sheets, "<<partial<<" partial atlases, "<<originals<<" originals retained; " << header.bytes << " bytes. Videos unchanged.\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
