// Network co-op guest: sends one local controller, or keyboard and mouse while its window
// has focus, to a hosting Darkwatch as player 2, plays the host's rumble and shows player
// 2's view and the game's sound, which the host streams as H.264 and PCM.
//   darkwatch_coop_client <host>[:port] <code>
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <winsock2.h>
#include <ws2tcpip.h>
#include <mstcpip.h>
#ifndef SIO_UDP_CONNRESET  // absent from some non-Microsoft headers
#define SIO_UDP_CONNRESET _WSAIOW(IOC_VENDOR, 12)
#endif
#include <windows.h>
#include <mmsystem.h>  // timeBeginPeriod; excluded by WIN32_LEAN_AND_MEAN
#include <SDL3/SDL.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <random>
#include <string>
#include <thread>
#include <vector>
#include "common/coop_protocol.h"
#include "common/coop_video.h"
#include "tools/coop_audio.h"
#include "tools/coop_frames.h"
#include "tools/coop_keys.h"

using namespace darkwatch::coop;

namespace {

std::atomic<bool> g_stop{false};
BOOL WINAPI OnConsole(DWORD) {g_stop = true; return TRUE;}

uint64_t NowUs() {
    using namespace std::chrono;
    return uint64_t(duration_cast<microseconds>(steady_clock::now().time_since_epoch()).count());
}
uint64_t NowMs() {return NowUs() / 1000;}

// Keyboard and mouse count only while this window has focus. Like a game, it holds and
// hides the cursor then; F8 or leaving the window releases it.
HWND g_window = nullptr;
bool g_grabbed = false, g_swallow_click = false;
int64_t g_mouse_dx = 0, g_mouse_dy = 0;

// The latest decoded picture of player 2's view; same thread as the window.
std::vector<uint8_t> g_picture;
uint32_t g_picture_w = 0, g_picture_h = 0;
uint64_t g_picture_ms = 0;
constexpr uint64_t kPictureStaleMs = 1500;  // then the instructions show again

void Grab(bool on) {
    g_grabbed = on;
    g_mouse_dx = g_mouse_dy = 0;
    if (on) {
        RECT r;
        GetClientRect(g_window, &r);
        MapWindowPoints(g_window, nullptr, reinterpret_cast<POINT*>(&r), 2);
        ClipCursor(&r);
        while (ShowCursor(FALSE) >= 0) {}
        g_swallow_click = true;  // the click that grabs is not a shot
    } else {
        ClipCursor(nullptr);
        while (ShowCursor(TRUE) < 0) {}
    }
    SetWindowTextW(g_window, on ? L"Darkwatch P2 - playing (F8 releases the mouse)"
                                : L"Darkwatch P2 - click here to play with keyboard and mouse");
}

LRESULT CALLBACK WindowProc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    switch (message) {
    case WM_INPUT: {
        RAWINPUT raw;
        UINT size = sizeof(raw);
        if (g_grabbed && GetRawInputData(reinterpret_cast<HRAWINPUT>(lparam), RID_INPUT, &raw, &size, sizeof(RAWINPUTHEADER)) != UINT(-1) &&
            raw.header.dwType == RIM_TYPEMOUSE && !(raw.data.mouse.usFlags & MOUSE_MOVE_ABSOLUTE)) {
            g_mouse_dx += raw.data.mouse.lLastX; g_mouse_dy += raw.data.mouse.lLastY;
        }
        break;
    }
    case WM_LBUTTONDOWN: if (!g_grabbed) Grab(true); return 0;
    case WM_KEYDOWN: if (wparam == VK_F8 && g_grabbed) Grab(false); return 0;
    case WM_ACTIVATE: if (LOWORD(wparam) == WA_INACTIVE && g_grabbed) Grab(false); break;
    case WM_CLOSE: g_stop = true; return 0;
    case WM_ERASEBKGND: return 1;  // WM_PAINT covers the whole client area
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        RECT r;
        GetClientRect(hwnd, &r);
        if (!g_picture.empty() && NowMs() - g_picture_ms < kPictureStaleMs) {
            // Letterboxed to the picture's aspect.
            const int cw = r.right, ch = r.bottom;
            int w = cw, h = int(int64_t(cw) * g_picture_h / g_picture_w);
            if (h > ch) {h = ch; w = int(int64_t(ch) * g_picture_w / g_picture_h);}
            const int x = (cw - w) / 2, y = (ch - h) / 2;
            HBRUSH black = static_cast<HBRUSH>(GetStockObject(BLACK_BRUSH));
            RECT bars[4]{{0, 0, cw, y}, {0, y + h, cw, ch}, {0, y, x, y + h}, {x + w, y, cw, y + h}};
            for (const RECT& bar : bars) FillRect(dc, &bar, black);
            BITMAPINFO bi{};
            bi.bmiHeader.biSize = sizeof(bi.bmiHeader);
            bi.bmiHeader.biWidth = LONG(g_picture_w);
            bi.bmiHeader.biHeight = -LONG(g_picture_h);  // top-down
            bi.bmiHeader.biPlanes = 1;
            bi.bmiHeader.biBitCount = 32;
            bi.bmiHeader.biCompression = BI_RGB;
            SetStretchBltMode(dc, COLORONCOLOR);
            StretchDIBits(dc, x, y, w, h, 0, 0, int(g_picture_w), int(g_picture_h), g_picture.data(), &bi,
                          DIB_RGB_COLORS, SRCCOPY);
            EndPaint(hwnd, &ps);
            return 0;
        }
        FillRect(dc, &r, static_cast<HBRUSH>(GetStockObject(BLACK_BRUSH)));
        SetTextColor(dc, RGB(220, 220, 220));
        SetBkMode(dc, TRANSPARENT);
        InflateRect(&r, -12, -10);
        DrawTextW(dc, L"Waiting for player 2's view from the host...\n\n"
                      L"Click here to play player 2 with keyboard and mouse. A controller always works.\n"
                      L"WASD move, mouse aims, left click fires, right click = left trigger, Space/E = A, B = B,\n"
                      L"R = X, Q = Y, G = Black, Shift = White, Esc/Enter = Start, Tab = Back, arrows = D-pad.\n"
                      L"F8 or Alt+Tab releases the mouse. Keys are not sent while this window is unfocused.",
                  -1, &r, DT_LEFT | DT_WORDBREAK);
        EndPaint(hwnd, &ps);
        return 0;
    }
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}

bool OpenWindow() {
    WNDCLASSW wc{};
    wc.lpfnWndProc = WindowProc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.hCursor = LoadCursorA(nullptr, IDC_ARROW);
    wc.hbrBackground = static_cast<HBRUSH>(GetStockObject(BLACK_BRUSH));
    wc.lpszClassName = L"DarkwatchCoopClient";
    if (!RegisterClassW(&wc)) return false;
    RECT size{0, 0, 1280, 720};  // client area of the streamed view
    AdjustWindowRect(&size, WS_OVERLAPPEDWINDOW, FALSE);
    g_window = CreateWindowExW(0, wc.lpszClassName, L"", WS_OVERLAPPEDWINDOW | WS_VISIBLE, CW_USEDEFAULT, CW_USEDEFAULT,
                               size.right - size.left, size.bottom - size.top, nullptr, nullptr, wc.hInstance, nullptr);
    if (!g_window) return false;
    Grab(false);  // sets the title
    RAWINPUTDEVICE mouse{1, 2, 0, g_window};  // generic desktop mouse, delivered while focused
    return RegisterRawInputDevices(&mouse, 1, sizeof(mouse));
}

bool KeyHeld(uint8_t key) {
    if (!g_grabbed || GetForegroundWindow() != g_window) return false;
    const bool down = (GetAsyncKeyState(key) & 0x8000) != 0;
    if (key == VK_LBUTTON && g_swallow_click) {
        if (!down) g_swallow_click = false;
        return false;
    }
    return down;
}

// Same layout as the runtime's input::Poll, so the host sees what a local pad would give.
PadState Read(SDL_Gamepad* pad) {
    constexpr SDL_GamepadButton kButtons[] = {
        SDL_GAMEPAD_BUTTON_DPAD_UP, SDL_GAMEPAD_BUTTON_DPAD_DOWN, SDL_GAMEPAD_BUTTON_DPAD_LEFT,
        SDL_GAMEPAD_BUTTON_DPAD_RIGHT, SDL_GAMEPAD_BUTTON_START, SDL_GAMEPAD_BUTTON_BACK,
        SDL_GAMEPAD_BUTTON_LEFT_STICK, SDL_GAMEPAD_BUTTON_RIGHT_STICK};
    constexpr SDL_GamepadButton kAnalog[] = {
        SDL_GAMEPAD_BUTTON_SOUTH, SDL_GAMEPAD_BUTTON_EAST, SDL_GAMEPAD_BUTTON_WEST, SDL_GAMEPAD_BUTTON_NORTH,
        SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER};
    PadState p;
    if (!pad) return p;
    auto axis = [&](SDL_GamepadAxis a) {return int(SDL_GetGamepadAxis(pad, a));};
    for (int i = 0; i < 8; i++) p.buttons |= uint16_t(SDL_GetGamepadButton(pad, kButtons[i]) << i);
    for (int i = 0; i < 6; i++) p.analog[i] = SDL_GetGamepadButton(pad, kAnalog[i]) ? 0xFF : 0;
    p.analog[6] = uint8_t(std::max(axis(SDL_GAMEPAD_AXIS_LEFT_TRIGGER), 0) >> 7);
    p.analog[7] = uint8_t(std::max(axis(SDL_GAMEPAD_AXIS_RIGHT_TRIGGER), 0) >> 7);
    p.lx = int16_t(axis(SDL_GAMEPAD_AXIS_LEFTX));
    p.ly = int16_t(-1 - axis(SDL_GAMEPAD_AXIS_LEFTY));
    p.rx = int16_t(axis(SDL_GAMEPAD_AXIS_RIGHTX));
    p.ry = int16_t(-1 - axis(SDL_GAMEPAD_AXIS_RIGHTY));
    return p;
}

bool Resolve(std::string target, sockaddr_in& out) {
    std::string port = std::to_string(kDefaultPort);
    if (auto colon = target.rfind(':'); colon != std::string::npos) {
        port = target.substr(colon + 1); target.resize(colon);
    }
    addrinfo hints{}, *result = nullptr;
    hints.ai_family = AF_INET; hints.ai_socktype = SOCK_DGRAM; hints.ai_protocol = IPPROTO_UDP;
    if (getaddrinfo(target.c_str(), port.c_str(), &hints, &result) || !result) return false;
    std::memcpy(&out, result->ai_addr, sizeof(out));
    freeaddrinfo(result);
    return true;
}

void Send(SOCKET s, const sockaddr_in& host, const Packet& packet) {
    uint8_t data[kMaxPacket];
    if (size_t size = Encode(packet, data))
        sendto(s, reinterpret_cast<const char*>(data), int(size), 0, reinterpret_cast<const sockaddr*>(&host), sizeof(host));
}

} // namespace

int main(int argc, char** argv) {
    if (argc != 3) {
        std::fprintf(stderr, "Usage: darkwatch_coop_client <host>[:port] <code>\n"
                             "The host sets coop_host = true and the same coop_code in darkwatch_xbe_settings.toml.\n");
        return 2;
    }
    Packet hello;
    hello.type = Type::Hello;
    if (!SetCode(hello, argv[2])) {std::fprintf(stderr, "The code must be 1-%zu bytes.\n", kCodeBytes); return 2;}
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa)) {std::fprintf(stderr, "Winsock is unavailable.\n"); return 1;}
    sockaddr_in host{};
    if (!Resolve(argv[1], host)) {std::fprintf(stderr, "Could not resolve %s.\n", argv[1]); return 1;}
    SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s == INVALID_SOCKET) {std::fprintf(stderr, "Could not open a UDP socket.\n"); return 1;}
    BOOL report = FALSE; DWORD bytes = 0;
    WSAIoctl(s, SIO_UDP_CONNRESET, &report, sizeof(report), nullptr, 0, &bytes, nullptr, nullptr);
    int receive_buffer = 2 << 20;  // a burst of video chunks while the window paints
    setsockopt(s, SOL_SOCKET, SO_RCVBUF, reinterpret_cast<const char*>(&receive_buffer), sizeof(receive_buffer));
    // Readable data or window input wakes the loop; the socket becomes non-blocking.
    WSAEVENT readable = WSACreateEvent();
    WSAEventSelect(s, readable, FD_READ);

    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");  // the game window usually has focus
    if (!SDL_Init(SDL_INIT_GAMEPAD)) {std::fprintf(stderr, "SDL: %s\n", SDL_GetError()); return 1;}
    SetConsoleCtrlHandler(OnConsole, TRUE);
    if (!OpenWindow()) std::fprintf(stderr, "The window could not open; controllers still work, without video.\n");
    timeBeginPeriod(1);  // an 8 ms wait, not the default 15.6 ms tick
    const bool video_ready = darkwatch::coop::video::Startup();
    if (!video_ready) std::fprintf(stderr, "Media Foundation is unavailable; no video.\n");
    std::unique_ptr<darkwatch::coop::video::Decoder> decoder;
    FrameAssembler frames;
    AudioPlayer sound;
    if (!sound.Open()) std::fprintf(stderr, "XAudio2 is unavailable; no sound.\n");
    std::vector<uint8_t> encoded;
    uint64_t key_requested = 0;

    hello.token = std::random_device{}() | 1u;
    uint32_t sequence = 0;
    bool joined = false;
    uint64_t hello_sent = 0, last_heard = 0;
    SDL_Gamepad* pad = nullptr;
    uint64_t tick_us = 0;
    constexpr uint64_t kInputIntervalUs = 8000;
    uint32_t mouse_x = 0, mouse_y = 0;
    std::printf("Connecting to %s ...\n", argv[1]);
    constexpr uint64_t kHostTimeoutMs = 3000;
    while (!g_stop) {
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {TranslateMessage(&msg); DispatchMessageW(&msg);}
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_EVENT_GAMEPAD_ADDED && !pad) {
                pad = SDL_OpenGamepad(event.gdevice.which);
                if (pad) std::printf("Controller: %s\n", SDL_GetGamepadName(pad));
            } else if (event.type == SDL_EVENT_GAMEPAD_REMOVED && pad && event.gdevice.which == SDL_GetGamepadID(pad)) {
                SDL_CloseGamepad(pad); pad = nullptr;
                std::printf("Controller disconnected; connect one to keep playing.\n");
            }
        }
        const uint64_t now = NowMs();
        uint8_t data[kMaxPacket + 1];
        int size;
        while ((size = recv(s, reinterpret_cast<char*>(data), sizeof(data), 0)) > 0) {
            Packet packet;
            if (!Decode(data, size_t(size), packet) || packet.token != hello.token) continue;
            last_heard = now;
            if (packet.type == Type::Welcome) {
                if (packet.status == Status::Accepted) {
                    if (!joined) std::printf("Joined as player 2. Ctrl+C leaves.\n");
                    joined = true;
                } else if (packet.status == Status::Busy) {
                    std::printf("The host already has a player 2; retrying...\n");
                } else {
                    std::fprintf(stderr, packet.status == Status::BadCode ? "The host rejected the code.\n"
                                                                          : "The host runs a different co-op version.\n");
                    g_stop = true;
                }
            } else if (packet.type == Type::Rumble && pad) {
                SDL_RumbleGamepad(pad, packet.left, packet.right, 200);  // refreshed by the host's keepalive
            } else if (packet.type == Type::Audio) {
                sound.Push(packet);
            } else if (packet.type == Type::Video && video_ready && g_window) {
                bool key = false;
                if (!frames.Add(packet, encoded, key)) continue;
                if (!decoder) decoder = darkwatch::coop::video::Decoder::Create();
                if (!decoder) {std::fprintf(stderr, "The H.264 decoder is unavailable; no video.\n"); continue;}
                const bool decoded = decoder->Decode(encoded.data(), encoded.size(), [&](const uint8_t* bgra, uint32_t w, uint32_t h) {
                    g_picture.assign(bgra, bgra + size_t(w) * h * 4);
                    g_picture_w = w; g_picture_h = h; g_picture_ms = now;
                    InvalidateRect(g_window, nullptr, FALSE);
                });
                if (!decoded) frames.Reset();  // resynchronise from the next key frame
            }
        }
        if (joined && (frames.NeedKey() || g_picture.empty()) && now - key_requested >= 250) {
            Packet request;
            request.type = Type::KeyRequest; request.token = hello.token; request.sequence = sequence;
            Send(s, host, request);
            key_requested = now;
        }
        if (joined && now - last_heard > kHostTimeoutMs) {
            joined = false;
            frames.Reset();
            sound.Reset();
            decoder.reset();  // the next session's stream starts over
            std::printf("Lost the host; reconnecting...\n");
        }
        if (!joined && now - hello_sent >= 500) {
            hello.sequence = sequence;
            Send(s, host, hello); hello_sent = now;
        }
        const uint64_t now_us = NowUs();
        // Raw counts go to the host as running totals for its direct mouse aim.
        mouse_x += uint32_t(g_mouse_dx); mouse_y += uint32_t(g_mouse_dy);
        g_mouse_dx = g_mouse_dy = 0;
        // Video wakes the loop for every datagram; input still goes out at a steady ~120 Hz.
        if (joined && now_us - tick_us >= kInputIntervalUs) {
            Packet state;
            state.type = Type::Pad; state.token = hello.token; state.sequence = ++sequence;
            state.pad = Read(pad);
            keys::Merge(state.pad, KeyHeld, 0, 0, 0);
            state.pad.mouse_x = mouse_x; state.pad.mouse_y = mouse_y;
            state.pad.mouse = g_grabbed && GetForegroundWindow() == g_window;
            tick_us = now_us;
            Send(s, host, state);
        }
        // Wakes on a datagram or window input, else at the next input tick.
        MsgWaitForMultipleObjects(1, &readable, FALSE, 8, QS_ALLINPUT);
        WSAResetEvent(readable);
    }
    if (joined) {
        Packet bye;
        bye.type = Type::Bye; bye.token = hello.token; bye.sequence = ++sequence;
        Send(s, host, bye);
    }
    if (g_window) {Grab(false); DestroyWindow(g_window);}
    if (pad) SDL_CloseGamepad(pad);
    SDL_Quit();
    sound.Close();
    decoder.reset();
    if (video_ready) darkwatch::coop::video::Shutdown();
    timeEndPeriod(1);
    WSACloseEvent(readable);
    closesocket(s);
    WSACleanup();
    return 0;
}
