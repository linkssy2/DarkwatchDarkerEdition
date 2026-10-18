#pragma once
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <wincodec.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace darkwatch::hd {
struct PngOverride {
    uint32_t native_offset = 0;
    std::string name;
    std::filesystem::path file;
    std::array<uint32_t,4> crop{}; // explicit source-pixel x,y,width,height
    bool contain = false;
};

inline bool LocalPng(const std::filesystem::path& directory, const std::filesystem::path& file) {
    if (file.empty() || file.is_absolute() || file.has_parent_path() || file.filename() != file) return false;
    auto extension=file.extension().wstring();
    for(auto& c:extension)if(c>=L'A'&&c<=L'Z')c+=L'a'-L'A';
    if(extension!=L".png")return false;
    const DWORD dir=GetFileAttributesW(directory.c_str()), attr=GetFileAttributesW((directory/file).c_str());
    return dir!=INVALID_FILE_ATTRIBUTES && (dir&FILE_ATTRIBUTE_DIRECTORY) && !(dir&FILE_ATTRIBUTE_REPARSE_POINT) &&
           attr!=INVALID_FILE_ATTRIBUTES && !(attr&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT));
}

// Exact aspect is the default. Explicit contain preserves the whole crop,
// uniformly scaled and centered on transparent padding; it never stretches.
inline bool ReadPng(IWICImagingFactory* factory, const std::filesystem::path& directory,
                    const PngOverride& item, uint32_t width, uint32_t height,
                    std::vector<uint8_t>& bgra, std::string& reason) {
    using Microsoft::WRL::ComPtr;
    auto fail=[&](const char* text){reason=text;return false;};
    if(!factory || !width || !height || width>4096 || height>4096)return fail("invalid output extent");
    if(!LocalPng(directory,item.file))return fail("missing PNG or unsafe path");
    std::error_code ec;const auto bytes=std::filesystem::file_size(directory/item.file,ec);
    if(ec || !bytes || bytes>(64u<<20))return fail("PNG file size");
    ComPtr<IWICBitmapDecoder> decoder;
    if(FAILED(factory->CreateDecoderFromFilename((directory/item.file).c_str(),nullptr,GENERIC_READ,
                  WICDecodeMetadataCacheOnLoad,&decoder)))return fail("PNG decode");
    GUID container{};UINT frames=0;
    if(FAILED(decoder->GetContainerFormat(&container)) || container!=GUID_ContainerFormatPng ||
       FAILED(decoder->GetFrameCount(&frames)) || frames!=1)return fail("not a single PNG frame");
    ComPtr<IWICBitmapFrameDecode> frame;
    UINT source_width=0,source_height=0;
    if(FAILED(decoder->GetFrame(0,&frame)) || FAILED(frame->GetSize(&source_width,&source_height)) ||
       !source_width || !source_height || source_width>4096 || source_height>4096)return fail("PNG dimensions");
    const auto& c=item.crop;
    if(!c[2] || !c[3] || uint64_t(c[0])+c[2]>source_width || uint64_t(c[1])+c[3]>source_height ||
       (!item.contain&&uint64_t(c[2])*height!=uint64_t(c[3])*width))return fail("crop bounds or original aspect mismatch");
    uint32_t scaled_width=width,scaled_height=height;
    if(item.contain){
        if(uint64_t(c[2])*height>uint64_t(c[3])*width)
            scaled_height=std::max(1u,uint32_t(uint64_t(c[3])*width/c[2]));
        else scaled_width=std::max(1u,uint32_t(uint64_t(c[2])*height/c[3]));
    }
    ComPtr<IWICBitmapClipper> clip;
    WICRect rect{INT(c[0]),INT(c[1]),INT(c[2]),INT(c[3])};
    if(FAILED(factory->CreateBitmapClipper(&clip)) || FAILED(clip->Initialize(frame.Get(),&rect)))return fail("PNG crop");
    // Resample coverage and premultiplied colour together, then store the runtime's
    // straight BGRA format. Transparent RGB must not bleed into visible edges.
    ComPtr<IWICFormatConverter> premultiplied;
    if(FAILED(factory->CreateFormatConverter(&premultiplied)) ||
       FAILED(premultiplied->Initialize(clip.Get(),GUID_WICPixelFormat32bppPBGRA,WICBitmapDitherTypeNone,
                                      nullptr,0,WICBitmapPaletteTypeCustom)))return fail("PNG alpha conversion");
    ComPtr<IWICBitmapScaler> scaler;
    if(FAILED(factory->CreateBitmapScaler(&scaler)) ||
       FAILED(scaler->Initialize(premultiplied.Get(),scaled_width,scaled_height,WICBitmapInterpolationModeFant)))return fail("PNG resize");
    ComPtr<IWICFormatConverter> straight;
    if(FAILED(factory->CreateFormatConverter(&straight)) ||
       FAILED(straight->Initialize(scaler.Get(),GUID_WICPixelFormat32bppBGRA,WICBitmapDitherTypeNone,
                                 nullptr,0,WICBitmapPaletteTypeCustom)))return fail("PNG output conversion");
    std::vector<uint8_t> pixels(size_t(scaled_width)*scaled_height*4);
    if(FAILED(straight->CopyPixels(nullptr,scaled_width*4,UINT(pixels.size()),pixels.data())))return fail("PNG pixel read");
    if(scaled_width!=width||scaled_height!=height){
        std::vector<uint8_t> padded(size_t(width)*height*4,0);
        const uint32_t x=(width-scaled_width)/2,y=(height-scaled_height)/2;
        for(uint32_t row=0;row<scaled_height;++row)std::copy_n(pixels.data()+size_t(row)*scaled_width*4,scaled_width*4,
            padded.data()+(size_t(y+row)*width+x)*4);
        pixels.swap(padded);
    }
    bgra.swap(pixels);reason.clear();return true;
}
} // namespace darkwatch::hd
