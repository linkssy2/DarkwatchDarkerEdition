#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <mfapi.h>
#include <mferror.h>
#include <mfidl.h>
#include <mftransform.h>
#include <codecapi.h>
#include <wmcodecdsp.h>
#include <wrl/client.h>
#include "common/coop_video.h"
#include <algorithm>
#include <cstring>

using Microsoft::WRL::ComPtr;

namespace darkwatch::coop::video {
namespace {

uint8_t Clip(int v) {return uint8_t(std::clamp(v, 0, 255));}

void SetCodec(ICodecAPI* codec, const GUID& key, UINT32 value) {
    if (!codec) return;
    VARIANT v;
    VariantInit(&v);
    v.vt = VT_UI4;
    v.ulVal = value;
    codec->SetValue(&key, &v);
}
void SetCodecBool(ICodecAPI* codec, const GUID& key, bool value) {
    if (!codec) return;
    VARIANT v;
    VariantInit(&v);
    v.vt = VT_BOOL;
    v.boolVal = value ? VARIANT_TRUE : VARIANT_FALSE;
    codec->SetValue(&key, &v);
}

ComPtr<IMFSample> MakeSample(DWORD bytes) {
    ComPtr<IMFSample> sample;
    ComPtr<IMFMediaBuffer> buffer;
    if (FAILED(MFCreateSample(&sample)) || FAILED(MFCreateMemoryBuffer(bytes, &buffer)) ||
        FAILED(sample->AddBuffer(buffer.Get()))) return nullptr;
    return sample;
}

bool Fill(IMFSample* sample, const uint8_t* data, size_t size) {
    ComPtr<IMFMediaBuffer> buffer;
    BYTE* dst = nullptr;
    if (FAILED(sample->GetBufferByIndex(0, &buffer)) || FAILED(buffer->Lock(&dst, nullptr, nullptr))) return false;
    std::memcpy(dst, data, size);
    buffer->Unlock();
    return SUCCEEDED(buffer->SetCurrentLength(DWORD(size)));
}

// Calls ProcessOutput until the transform wants input. `got` sees each produced sample.
// A stream change lets `renegotiate` set the output type again.
template <class Got, class Renegotiate>
bool Drain(IMFTransform* mft, Got got, Renegotiate renegotiate) {
    for (;;) {
        MFT_OUTPUT_STREAM_INFO info{};
        if (FAILED(mft->GetOutputStreamInfo(0, &info))) return false;
        MFT_OUTPUT_DATA_BUFFER out{};
        ComPtr<IMFSample> sample;
        if (!(info.dwFlags & (MFT_OUTPUT_STREAM_PROVIDES_SAMPLES | MFT_OUTPUT_STREAM_CAN_PROVIDE_SAMPLES))) {
            sample = MakeSample(std::max<DWORD>(info.cbSize, 1 << 20));
            if (!sample) return false;
            out.pSample = sample.Get();
        }
        DWORD status = 0;
        const HRESULT hr = mft->ProcessOutput(0, 1, &out, &status);
        if (out.pEvents) out.pEvents->Release();
        if (hr == MF_E_TRANSFORM_NEED_MORE_INPUT) return true;
        if (hr == MF_E_TRANSFORM_STREAM_CHANGE) {
            if (!renegotiate()) return false;
            continue;
        }
        if (FAILED(hr)) return false;
        if (!sample && out.pSample) sample.Attach(out.pSample);  // the transform's own sample
        if (sample) got(sample.Get());
    }
}

class MfEncoder final : public Encoder {
public:
    bool Init(uint32_t width, uint32_t height, uint32_t fps, uint32_t bitrate) {
        width_ = width; height_ = height; fps_ = fps;
        if (FAILED(CoCreateInstance(CLSID_MSH264EncoderMFT, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&mft_)))) return false;
        mft_.As(&codec_);
        // Interactive: one frame in, one out, constant rate, IDR only on request after the first.
        SetCodecBool(codec_.Get(), CODECAPI_AVLowLatencyMode, true);
        SetCodec(codec_.Get(), CODECAPI_AVEncCommonRateControlMode, eAVEncCommonRateControlMode_CBR);
        SetCodec(codec_.Get(), CODECAPI_AVEncCommonMeanBitRate, bitrate);
        SetCodec(codec_.Get(), CODECAPI_AVEncCommonQualityVsSpeed, 0);
        SetCodec(codec_.Get(), CODECAPI_AVEncMPVDefaultBPictureCount, 0);
        SetCodec(codec_.Get(), CODECAPI_AVEncMPVGOPSize, fps * 4);
        ComPtr<IMFMediaType> out, in;
        if (FAILED(MFCreateMediaType(&out)) || FAILED(MFCreateMediaType(&in))) return false;
        out->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
        out->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_H264);
        out->SetUINT32(MF_MT_AVG_BITRATE, bitrate);
        out->SetUINT32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive);
        out->SetUINT32(MF_MT_MPEG2_PROFILE, eAVEncH264VProfile_Base);
        MFSetAttributeSize(out.Get(), MF_MT_FRAME_SIZE, width, height);
        MFSetAttributeRatio(out.Get(), MF_MT_FRAME_RATE, fps, 1);
        MFSetAttributeRatio(out.Get(), MF_MT_PIXEL_ASPECT_RATIO, 1, 1);
        if (FAILED(mft_->SetOutputType(0, out.Get(), 0))) return false;
        in->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
        in->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_NV12);
        in->SetUINT32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive);
        MFSetAttributeSize(in.Get(), MF_MT_FRAME_SIZE, width, height);
        MFSetAttributeRatio(in.Get(), MF_MT_FRAME_RATE, fps, 1);
        MFSetAttributeRatio(in.Get(), MF_MT_PIXEL_ASPECT_RATIO, 1, 1);
        if (FAILED(mft_->SetInputType(0, in.Get(), 0))) return false;
        mft_->ProcessMessage(MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0);
        mft_->ProcessMessage(MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0);
        return true;
    }

    bool Encode(const std::vector<uint8_t>& nv12, bool force_key, const EncodedFrame& out) override {
        if (nv12.size() != size_t(width_) * height_ * 3 / 2) return false;
        ComPtr<IMFSample> sample = MakeSample(DWORD(nv12.size()));
        if (!sample || !Fill(sample.Get(), nv12.data(), nv12.size())) return false;
        const LONGLONG duration = 10'000'000 / fps_;
        sample->SetSampleTime(frames_ * duration);
        sample->SetSampleDuration(duration);
        ++frames_;
        if (force_key) SetCodec(codec_.Get(), CODECAPI_AVEncVideoForceKeyFrame, 1);
        auto got = [&](IMFSample* s) {
            ComPtr<IMFMediaBuffer> buffer;
            BYTE* data = nullptr;
            DWORD length = 0;
            if (FAILED(s->ConvertToContiguousBuffer(&buffer)) || FAILED(buffer->Lock(&data, nullptr, &length))) return;
            out(data, length, MFGetAttributeUINT32(s, MFSampleExtension_CleanPoint, FALSE) != 0);
            buffer->Unlock();
        };
        auto renegotiate = [&] {
            ComPtr<IMFMediaType> type;
            return SUCCEEDED(mft_->GetOutputAvailableType(0, 0, &type)) && SUCCEEDED(mft_->SetOutputType(0, type.Get(), 0));
        };
        HRESULT hr = mft_->ProcessInput(0, sample.Get(), 0);
        if (hr == MF_E_NOTACCEPTING) {
            if (!Drain(mft_.Get(), got, renegotiate)) return false;
            hr = mft_->ProcessInput(0, sample.Get(), 0);
        }
        return SUCCEEDED(hr) && Drain(mft_.Get(), got, renegotiate);
    }

private:
    ComPtr<IMFTransform> mft_;
    ComPtr<ICodecAPI> codec_;
    uint32_t width_ = 0, height_ = 0, fps_ = 60;
    LONGLONG frames_ = 0;
};

class MfDecoder final : public Decoder {
public:
    bool Init() {
        if (FAILED(CoCreateInstance(CLSID_CMSH264DecoderMFT, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&mft_)))) return false;
        // Without low latency the decoder holds a reorder window of frames before output.
        ComPtr<IMFAttributes> attributes;
        if (SUCCEEDED(mft_->GetAttributes(&attributes))) attributes->SetUINT32(MF_LOW_LATENCY, TRUE);
        ComPtr<ICodecAPI> codec;
        if (SUCCEEDED(mft_.As(&codec))) SetCodecBool(codec.Get(), CODECAPI_AVLowLatencyMode, true);
        ComPtr<IMFMediaType> in;
        if (FAILED(MFCreateMediaType(&in))) return false;
        in->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
        in->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_H264);
        if (FAILED(mft_->SetInputType(0, in.Get(), 0)) || !SetOutput()) return false;
        mft_->ProcessMessage(MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0);
        mft_->ProcessMessage(MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0);
        return true;
    }

    bool Decode(const uint8_t* data, size_t size, const DecodedFrame& out) override {
        ComPtr<IMFSample> sample = MakeSample(DWORD(size));
        if (!sample || !Fill(sample.Get(), data, size)) return false;
        auto got = [&](IMFSample* s) {
            if (!width_ || !height_) return;
            ComPtr<IMFMediaBuffer> buffer;
            BYTE* px = nullptr;
            DWORD length = 0;
            if (FAILED(s->ConvertToContiguousBuffer(&buffer)) || FAILED(buffer->Lock(&px, nullptr, &length))) return;
            const uint32_t rows = stride_ ? uint32_t(length * 2 / 3 / stride_) : 0;
            if (rows >= height_) {
                Nv12ToBgra(px, stride_, rows, width_, height_, bgra_);
                buffer->Unlock();
                out(bgra_.data(), width_, height_);
                return;
            }
            buffer->Unlock();
        };
        HRESULT hr = mft_->ProcessInput(0, sample.Get(), 0);
        if (hr == MF_E_NOTACCEPTING) {
            if (!Drain(mft_.Get(), got, [&] {return SetOutput();})) return false;
            hr = mft_->ProcessInput(0, sample.Get(), 0);
        }
        return SUCCEEDED(hr) && Drain(mft_.Get(), got, [&] {return SetOutput();});
    }

private:
    // NV12 output; the picture size comes from the display aperture when the coded size is padded.
    bool SetOutput() {
        for (DWORD i = 0;; ++i) {
            ComPtr<IMFMediaType> type;
            if (FAILED(mft_->GetOutputAvailableType(0, i, &type))) return false;
            GUID subtype{};
            if (FAILED(type->GetGUID(MF_MT_SUBTYPE, &subtype)) || subtype != MFVideoFormat_NV12) continue;
            if (FAILED(mft_->SetOutputType(0, type.Get(), 0))) return false;
            UINT32 w = 0, h = 0;
            MFGetAttributeSize(type.Get(), MF_MT_FRAME_SIZE, &w, &h);
            stride_ = MFGetAttributeUINT32(type.Get(), MF_MT_DEFAULT_STRIDE, w);
            width_ = w; height_ = h;
            MFVideoArea area{};
            if (SUCCEEDED(type->GetBlob(MF_MT_MINIMUM_DISPLAY_APERTURE, reinterpret_cast<UINT8*>(&area), sizeof(area), nullptr)) &&
                area.Area.cx > 0 && area.Area.cy > 0 && UINT32(area.Area.cx) <= w && UINT32(area.Area.cy) <= h) {
                width_ = UINT32(area.Area.cx); height_ = UINT32(area.Area.cy);
            }
            width_ &= ~1u; height_ &= ~1u;
            return true;
        }
    }

    ComPtr<IMFTransform> mft_;
    uint32_t width_ = 0, height_ = 0, stride_ = 0;
    std::vector<uint8_t> bgra_;
};

} // namespace

bool Startup() {
    const HRESULT com = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(com) && com != RPC_E_CHANGED_MODE) return false;
    return SUCCEEDED(MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET));
}
void Shutdown() {
    MFShutdown();
    CoUninitialize();
}

void BgraToNv12(const uint8_t* bgra, uint32_t pitch, uint32_t width, uint32_t height, std::vector<uint8_t>& nv12) {
    nv12.resize(size_t(width) * height * 3 / 2);
    uint8_t* y = nv12.data();
    uint8_t* uv = y + size_t(width) * height;
    for (uint32_t row = 0; row < height; row += 2) {
        for (uint32_t col = 0; col < width; col += 2) {
            int sb = 0, sg = 0, sr = 0;
            for (uint32_t dy = 0; dy < 2; ++dy)
                for (uint32_t dx = 0; dx < 2; ++dx) {
                    const uint8_t* p = bgra + size_t(row + dy) * pitch + size_t(col + dx) * 4;
                    const int b = p[0], g = p[1], r = p[2];
                    y[size_t(row + dy) * width + col + dx] = Clip(((66 * r + 129 * g + 25 * b + 128) >> 8) + 16);
                    sb += b; sg += g; sr += r;
                }
            sb /= 4; sg /= 4; sr /= 4;
            uint8_t* c = uv + size_t(row / 2) * width + col;
            c[0] = Clip(((-38 * sr - 74 * sg + 112 * sb + 128) >> 8) + 128);
            c[1] = Clip(((112 * sr - 94 * sg - 18 * sb + 128) >> 8) + 128);
        }
    }
}

void Nv12ToBgra(const uint8_t* nv12, uint32_t stride, uint32_t rows, uint32_t width, uint32_t height,
                std::vector<uint8_t>& bgra) {
    bgra.resize(size_t(width) * height * 4);
    const uint8_t* uv = nv12 + size_t(stride) * rows;
    for (uint32_t row = 0; row < height; ++row) {
        const uint8_t* y = nv12 + size_t(row) * stride;
        const uint8_t* c = uv + size_t(row / 2) * stride;
        uint8_t* out = bgra.data() + size_t(row) * width * 4;
        for (uint32_t col = 0; col < width; ++col) {
            const int luma = 298 * (y[col] - 16), d = c[col & ~1u] - 128, e = c[(col & ~1u) + 1] - 128;
            out[col * 4 + 0] = Clip((luma + 516 * d + 128) >> 8);
            out[col * 4 + 1] = Clip((luma - 100 * d - 208 * e + 128) >> 8);
            out[col * 4 + 2] = Clip((luma + 409 * e + 128) >> 8);
            out[col * 4 + 3] = 255;
        }
    }
}

std::unique_ptr<Encoder> Encoder::Create(uint32_t width, uint32_t height, uint32_t fps, uint32_t bitrate) {
    if (!width || !height || (width | height) & 1 || !fps) return nullptr;
    auto encoder = std::make_unique<MfEncoder>();
    if (!encoder->Init(width, height, fps, bitrate)) return nullptr;
    return encoder;
}

std::unique_ptr<Decoder> Decoder::Create() {
    auto decoder = std::make_unique<MfDecoder>();
    if (!decoder->Init()) return nullptr;
    return decoder;
}

} // namespace darkwatch::coop::video
