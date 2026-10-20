#pragma once
// Guest side of the co-op video: shows decoded frames through a Direct3D 11 swap chain sized
// to the video, which DXGI stretches to the window. It uses the blt model: flip-model chains
// may be promoted to a hardware overlay plane, where some drivers showed the picture green.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <wrl/client.h>
#include <cstdint>

namespace darkwatch::coop {

class Presenter {
public:
    // Copies one top-down BGRA frame to the window; the swap chain follows the frame size.
    bool Show(HWND window, const uint8_t* bgra, uint32_t width, uint32_t height) {
        if (!Ensure(window, width, height)) return false;
        Microsoft::WRL::ComPtr<ID3D11Texture2D> back;
        if (FAILED(swap_->GetBuffer(0, IID_PPV_ARGS(&back)))) return false;
        context_->UpdateSubresource(back.Get(), 0, nullptr, bgra, width * 4, 0);
        // No vsync wait: the picture is shown as soon as it is decoded.
        return SUCCEEDED(swap_->Present(0, 0));
    }
    bool Active() const {return swap_ != nullptr;}

private:
    bool Ensure(HWND window, uint32_t width, uint32_t height) {
        if (swap_ && width == width_ && height == height_) return true;
        if (swap_) {
            context_->ClearState();
            if (FAILED(swap_->ResizeBuffers(0, width, height, DXGI_FORMAT_UNKNOWN, 0))) return false;
            width_ = width; height_ = height;
            return true;
        }
        if (FAILED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0,
                                     D3D11_SDK_VERSION, &device_, nullptr, &context_))) return false;
        Microsoft::WRL::ComPtr<IDXGIDevice> dxgi;
        Microsoft::WRL::ComPtr<IDXGIAdapter> adapter;
        Microsoft::WRL::ComPtr<IDXGIFactory2> factory;
        if (FAILED(device_.As(&dxgi)) || FAILED(dxgi->GetAdapter(&adapter)) || FAILED(adapter->GetParent(IID_PPV_ARGS(&factory))))
            return false;
        DXGI_SWAP_CHAIN_DESC1 desc{};
        desc.Width = width; desc.Height = height;
        desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        desc.BufferCount = 1;
        desc.Scaling = DXGI_SCALING_STRETCH;
        desc.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
        desc.AlphaMode = DXGI_ALPHA_MODE_IGNORE;
        if (FAILED(factory->CreateSwapChainForHwnd(device_.Get(), window, &desc, nullptr, nullptr, &swap_))) return false;
        factory->MakeWindowAssociation(window, DXGI_MWA_NO_ALT_ENTER);
        width_ = width; height_ = height;
        return true;
    }

    Microsoft::WRL::ComPtr<ID3D11Device> device_;
    Microsoft::WRL::ComPtr<ID3D11DeviceContext> context_;
    Microsoft::WRL::ComPtr<IDXGISwapChain1> swap_;
    uint32_t width_ = 0, height_ = 0;
};

} // namespace darkwatch::coop
