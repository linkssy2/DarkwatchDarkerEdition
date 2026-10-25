#include "language.h"
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <map>
#include <vector>
#include <toml++/toml.hpp>

namespace darkwatch::language {
namespace {
bool requested = false;
std::atomic<bool> enabled{false};
using Lines = std::map<uint64_t, std::string>;
Lines catalogue;
uint64_t ContextId(uint32_t key, std::string_view original) {
    // Lookup identity only; the launcher validates the resource's SHA-256.
    uint64_t value = 14695981039346656037ull;
    for (unsigned i = 0; i < 4; ++i) value = (value ^ uint8_t(key >> (i * 8))) * 1099511628211ull;
    for (const unsigned char c : original) value = (value ^ c) * 1099511628211ull;
    return value;
}
struct Copy {const char* english; const char* spanish;};
constexpr Copy copy[]{
    {"MUSIC VOLUME", "VOLUMEN DE MÚSICA"},
    {"EFFECTS VOLUME", "VOLUMEN DE EFECTOS"},
    {"SPEECH VOLUME", "VOLUMEN DE VOCES"},
    {"SOUND OUTPUT", "SALIDA DE AUDIO"},
    {"Stereo", "Estéreo"},
    {"Surround", "Envolvente"},
    {"Surround uses your device's 5.1 or 7.1 speakers.", "Usa los altavoces 5.1 o 7.1 de tu dispositivo."},
    {"Surround unavailable. Set up 5.1 or 7.1 speakers, then restart.", "Configura altavoces 5.1 o 7.1 y reinicia para usar sonido envolvente."},
    {"Could not apply audio settings. Reopen Audio and try again.", "No se pudo aplicar el audio. Vuelve a abrir Audio e inténtalo de nuevo."},
    {"Audio applied. Profile volumes save when you leave Options.", "Audio aplicado. Los volúmenes se guardan al salir de Opciones."},
    {"Audio defaults restored in this draft. Select Apply to save.", "Audio restablecido. Selecciona Aplicar para guardar."},
    {"Cannot apply these controller bindings.", "No se pueden aplicar estas asignaciones del mando."},
    {"Buttons swapped in this draft. Apply from Controls to save.", "Botones intercambiados. Aplica desde Controles para guardar."},
    {"Connect this player's controller to change buttons.", "Conecta el mando de este jugador para cambiar los botones."},
    {"Press a controller button. Start + Back or Escape cancels.", "Pulsa un botón. Start + Back o Escape para cancelar."},
    {"Select an action to change its button. Menu buttons stay unchanged.", "Elige una acción para cambiar su botón. No afecta a los menús."},
    {"RESET BUTTONS", "RESTABLECER BOTONES"},
    {"Controller buttons reset in this draft. Apply from Controls to save.", "Botones restablecidos. Aplica desde Controles para guardar."},
    {"Player 2 settings. Use Controller Layout to change buttons.", "Ajustes del jugador 2. Cambia los botones en Configuración del mando."},
    {"Could not change co-op selection. Try again.", "No se pudo cambiar la selección. Inténtalo de nuevo."},
    {"Preview unavailable.", "Vista previa no disponible."},
    {"READY", "LISTO"},
    {"CANCEL READY", "NO ESTOY LISTO"},
    {"CONNECT CONTROLLER", "CONECTA EL MANDO"},
    {"Both players ready to continue.", "Ambos jugadores deben estar listos."},
    {"ARROWS: MOVE   ENTER: SELECT   ESC: BACK", "FLECHAS: MOVER   INTRO: ELEGIR   ESC: VOLVER"},
    {"D-PAD: MOVE", "CRUCETA: MOVER"},
    {"SELECT", "ELEGIR"},
    {"GRAPHICS", "GRÁFICOS"},
    {"CONTROLS", "CONTROLES"},
    {"CHARACTERS", "PERSONAJES"},
    {"CHOOSE CHARACTER", "ELIGE PERSONAJE"},
    {"Preview unavailable. Verify files in the launcher.", "Vista previa no disponible. Verifica los archivos en el lanzador."},
    {"Character", "Personaje"},
    {"PREVIOUS", "ANTERIOR"},
    {"NEXT", "SIGUIENTE"},
    {"CONTINUE", "CONTINUAR"},
    {"Choose your single-player character.", "Elige tu personaje para un jugador."},
    {"Continue to choose a chapter or resume your save.", "Continúa para elegir un capítulo o reanudar tu partida."},
    {"Replay this chapter? Your saved campaign progress will be kept.", "¿Repetir este capítulo? Se conservará el progreso de tu campaña."},
    {"Could not open Single Player. Try again.", "No se pudo abrir Un jugador. Inténtalo de nuevo."},
    {"CHARACTER SELECTED FOR THIS SESSION. COULD NOT SAVE SETTINGS.", "PERSONAJE ELEGIDO PARA ESTA SESIÓN. NO SE PUDO GUARDAR."},
    {"COULD NOT PREPARE CAMPAIGN. RESTART THE GAME AND TRY AGAIN.", "NO SE PUDO PREPARAR LA CAMPAÑA. REINICIA EL JUEGO E INTÉNTALO DE NUEVO."},
    {"QUIT TO DESKTOP", "SALIR DEL JUEGO"},
    {"CO-OP", "COOPERATIVO"},
    {"CONTROLLER LAYOUT", "CONFIGURACIÓN DEL MANDO"},
    {"CONTROLLER LAYOUT...", "MANDO..."},
    {"PLAYSTATION CONTROLLER", "MANDO PLAYSTATION"},
    {"SWITCH CONTROLLER", "MANDO SWITCH"},
    {"XBOX CONTROLLER", "MANDO XBOX"},
    {"BACK", "VOLVER"},
    {"APPLY", "APLICAR"},
    {"KEEP", "CONSERVAR"},
    {"REVERT", "REVERTIR"},
    {"CANCEL", "CANCELAR"},
    {"QUIT", "SALIR"},
    {"REPLACE", "REEMPLAZAR"},
    {"RESET DEFAULTS", "RESTABLECER"},
    {"RESET VIEW DEFAULTS", "RESTABLECER VISTA"},
    {"PLAYER ONE", "JUGADOR 1"},
    {"PLAYER TWO", "JUGADOR 2"},
    {"Spectral Cassidy", "Cassidy espectral"},
    {"Civilian Jericho", "Jericho civil"},
    {"Darkwatch Trooper", "Soldado Darkwatch"},
    {"Blue Trooper", "Soldado azul"},
    {"Red Trooper", "Soldado rojo"},
    {"Quit to desktop?", "¿Salir al escritorio?"},
    {"Could not quit. Try again.", "No se pudo salir. Inténtalo de nuevo."},
    {"DISPLAY MODE", "MODO DE PANTALLA"},
    {"RESOLUTION", "RESOLUCIÓN"},
    {"ASPECT RATIO", "RELACIÓN DE ASPECTO"},
    {"RENDER RESOLUTION", "RESOLUCIÓN INTERNA"},
    {"FIELD OF VIEW", "CAMPO DE VISIÓN"},
    {"WEAPON FOV", "FOV DEL ARMA"},
    {"RETICLE SIZE", "TAMAÑO DE LA MIRA"},
    {"CUTSCENE BORDERS", "BANDAS DE ESCENAS"},
    {"FPS COUNTER", "CONTADOR DE FPS"},
    {"VERTICAL SYNC", "SINCRONIZACIÓN VERT."},
    {"FPS LIMIT", "LÍMITE DE FPS"},
    {"TEXTURE FILTERING", "FILTRADO DE TEXTURAS"},
    {"HD ARTWORK", "INTERFAZ HD"},
    {"SUBTITLES", "SUBTÍTULOS"},
    {"BRIGHTNESS", "BRILLO"},
    {"HD TEXTURES", "TEXTURAS HD"},
    {"MOUSE SENSITIVITY", "SENSIBILIDAD DEL RATÓN"},
    {"ZOOM SENSITIVITY", "SENSIBILIDAD DEL ZOOM"},
    {"AIMING ASSISTANCE", "AYUDA AL APUNTAR"},
    {"LOOK CENTERING", "CENTRAR VISTA"},
    {"INVERT LOOK", "INVERTIR VISTA"},
    {"PAD VIBRATION", "VIBRACIÓN DEL MANDO"},
    {"PAD SENSITIVITY", "SENSIBILIDAD DEL MANDO"},
    {"KEYBOARD AND MOUSE BINDINGS", "TECLADO Y RATÓN"},
    {"ACTION", "ACCIÓN"},
    {"PRIMARY", "PRIM."},
    {"ALT KEY", "ALT."},
    {"PRESS A KEY...", "PULSA UNA TECLA..."},
    {"Default", "Predet."},
    {"Chieftain", "Jefe"},
    {"Lefty", "Zurdo"},
    {"Hopalong", "Saltarín"},
    {"Hoss", "Forzudo"},
    {"Off", "No"},
    {"On", "Sí"},
    {"Fullscreen", "Pantalla completa"},
    {"Borderless", "Sin bordes"},
    {"Windowed", "Ventana"},
    {"Automatic", "Automática"},
    {"Widescreen 16:9", "Panorámica 16:9"},
    {"Unlimited", "Sin límite"},
    {"  (Desktop)", "  (Escritorio)"},
    {"Unbound", "Sin asignar"},
    {"Mouse 1", "Ratón 1"},
    {"Mouse 2", "Ratón 2"},
    {"Mouse 3", "Ratón 3"},
    {"Mouse 4", "Ratón 4"},
    {"Mouse 5", "Ratón 5"},
    {"Mouse Wheel", "Rueda del ratón"},
    {"Key %u", "Tecla %u"},
    {"D-PAD UP", "CRUCETA ARRIBA"},
    {"D-PAD DOWN", "CRUCETA ABAJO"},
    {"D-PAD LEFT", "CRUCETA IZQUIERDA"},
    {"D-PAD RIGHT", "CRUCETA DERECHA"},
    {"LEFT STICK CLICK", "PULSAR STICK IZQ."},
    {"RIGHT STICK CLICK", "PULSAR STICK DER."},
    {"A BUTTON", "BOTÓN A"},
    {"B BUTTON", "BOTÓN B"},
    {"X BUTTON", "BOTÓN X"},
    {"Y BUTTON", "BOTÓN Y"},
    {"BLACK BUTTON", "BOTÓN NEGRO"},
    {"WHITE BUTTON", "BOTÓN BLANCO"},
    {"LEFT TRIGGER", "GATILLO IZQUIERDO"},
    {"RIGHT TRIGGER", "GATILLO DERECHO"},
    {"MOVE FORWARD", "AVANZAR"},
    {"MOVE BACKWARD", "RETROCEDER"},
    {"MOVE LEFT", "MOVERSE A LA IZQ."},
    {"MOVE RIGHT", "MOVERSE A LA DER."},
    {"LEFT STICK UP", "STICK IZQ. ARRIBA"},
    {"LEFT STICK DOWN", "STICK IZQ. ABAJO"},
    {"LEFT STICK LEFT", "STICK IZQ. IZQUIERDA"},
    {"LEFT STICK RIGHT", "STICK IZQ. DERECHA"},
    {"LOOK UP", "MIRAR ARRIBA"},
    {"LOOK DOWN", "MIRAR ABAJO"},
    {"LOOK LEFT", "MIRAR A LA IZQUIERDA"},
    {"LOOK RIGHT", "MIRAR A LA DERECHA"},
    {"LOOK / AIM", "MIRAR / APUNTAR"},
    {"MOVE", "MOVERSE"},
    {"MULTIPLAYER TALK", "CHAT DE VOZ"},
    {"SWITCH WEAPONS", "CAMBIAR DE ARMA"},
    {"LEAN LEFT", "INCLINARSE A LA IZQ."},
    {"LEAN RIGHT", "INCLINARSE A LA DER."},
    {"PAUSE", "PAUSA"},
    {"MULTIPLAYER SCORE", "MARCADOR MULTIJUGADOR"},
    {"CROUCH", "AGACHARSE"},
    {"SIGHT MODE", "APUNTAR"},
    {"INTERACT", "INTERACTUAR"},
    {"RELOAD", "RECARGAR"},
    {"MELEE", "GOLPE CUERPO A CUERPO"},
    {"JUMP", "SALTAR"},
    {"POWER SELECTION", "ELEGIR PODER"},
    {"ACTIVATE POWER", "ACTIVAR PODER"},
    {"THROW", "LANZAR"},
    {"SHOOT", "DISPARAR"},
    {"Navigate up with the original D-pad.", "Arriba en la cruceta original."},
    {"Navigate down with the original D-pad.", "Abajo en la cruceta original."},
    {"Navigate left with the original D-pad.", "Izquierda en la cruceta original."},
    {"Navigate right with the original D-pad.", "Derecha en la cruceta original."},
    {"Open the original pause menu.", "Abrir el menú de pausa original."},
    {"Send the original Xbox Back action.", "Activar el botón Back original de Xbox."},
    {"Send the left-stick button action.", "Pulsar el stick izquierdo."},
    {"Send the right-stick button action.", "Pulsar el stick derecho."},
    {"Select in menus; gameplay uses your controller layout.", "Seleccionar en menús; al jugar se usa la configuración del mando."},
    {"Go back in menus; gameplay uses your controller layout.", "Volver en menús; al jugar se usa la configuración del mando."},
    {"Send the original Xbox X action.", "Activar el botón X original de Xbox."},
    {"Send the original Xbox Y action.", "Activar el botón Y original de Xbox."},
    {"Send the original Xbox Black action.", "Activar el botón negro original de Xbox."},
    {"Send the original Xbox White action.", "Activar el botón blanco original de Xbox."},
    {"Send the original left-trigger action.", "Activar el gatillo izquierdo original."},
    {"Send the original right-trigger action.", "Activar el gatillo derecho original."},
    {"Move forward with the left stick.", "Avanzar con el stick izquierdo."},
    {"Move backward with the left stick.", "Retroceder con el stick izquierdo."},
    {"Strafe left with the left stick.", "Moverse a la izquierda con el stick izquierdo."},
    {"Strafe right with the left stick.", "Moverse a la derecha con el stick izquierdo."},
    {"Original left stick up; see controller layout.", "Stick izquierdo arriba; consulta la configuración del mando."},
    {"Original left stick down; see controller layout.", "Stick izquierdo abajo; consulta la configuración del mando."},
    {"Original left stick left; see controller layout.", "Stick izquierdo a la izquierda; consulta la configuración del mando."},
    {"Original left stick right; see controller layout.", "Stick izquierdo a la derecha; consulta la configuración del mando."},
    {"Look up with the Lefty layout.", "Mirar arriba con la configuración Zurdo."},
    {"Look down with the Lefty layout.", "Mirar abajo con la configuración Zurdo."},
    {"Look left with the Lefty layout.", "Mirar a la izquierda con la configuración Zurdo."},
    {"Look right with the Lefty layout.", "Mirar a la derecha con la configuración Zurdo."},
    {"Talk in multiplayer.", "Hablar en multijugador."},
    {"Swap between your carried weapons.", "Cambiar entre tus armas."},
    {"Lean to the left.", "Inclinarse a la izquierda."},
    {"Lean to the right.", "Inclinarse a la derecha."},
    {"Open the pause menu.", "Abrir el menú de pausa."},
    {"Show multiplayer scores.", "Mostrar el marcador multijugador."},
    {"Crouch.", "Agacharse."},
    {"Use your weapon's sight mode.", "Apuntar con la mira del arma."},
    {"Interact with objects.", "Interactuar con objetos."},
    {"Reload your weapon.", "Recargar el arma."},
    {"Perform a melee attack.", "Dar un golpe cuerpo a cuerpo."},
    {"Jump.", "Saltar."},
    {"Select a power.", "Elegir un poder."},
    {"Activate your selected power.", "Activar el poder elegido."},
    {"Throw.", "Lanzar."},
    {"Fire your weapon.", "Disparar el arma."},
    {"Move the stick in the direction you want to go.", "Mueve el stick en la dirección deseada."},
    {"Apply layout changes from Controls.", "Aplica los cambios en Controles."},
    {"Mouse speed while zoomed. 100%% keeps your normal speed.", "Velocidad del ratón con zoom. 100%% conserva la velocidad normal."},
    {"Aiming assistance attracts the view near targets. Look centering recenters your view.", "La ayuda al apuntar acerca la mira al objetivo. Centrar vista la devuelve al centro."},
    {"Original settings are unavailable on this page.", "Los ajustes originales no están disponibles aquí."},
    {"Current: %s", "Actual: %s"},
    {"Player 2 controller settings. Controller Layout offers five control schemes.", "Ajustes del mando del jugador 2. Hay cinco configuraciones del mando."},
    {"Select a binding, then press a key, mouse button, or scroll the wheel. Escape cancels; Backspace clears.", "Elige una acción y pulsa una tecla, un botón del ratón o gira la rueda. Esc cancela; Retroceso borra."},
    {"Press a key, mouse button, or scroll the wheel. Escape cancels; Backspace clears.", "Pulsa una tecla, un botón del ratón o gira la rueda. Esc cancela; Retroceso borra."},
    {"%s is assigned to %s. Replace that assignment?", "%s está asignado a %s. ¿Reemplazar la asignación?"},
    {"PC defaults restored in this draft. Select Apply to save.", "Ajustes de PC restablecidos. Pulsa Aplicar para guardar."},
    {"Player one: single-player and co-op. Player two: co-op only.", "Jugador 1: individual y cooperativo. Jugador 2: solo cooperativo."},
    {"Spectral Cassidy is available from the start.\nCassidy follows the story for player two.", "Cassidy espectral está disponible desde el inicio.\nCassidy sigue la historia para el jugador 2."},
    {"Changes take effect when you start your next mission.", "Los cambios se aplicarán en la próxima misión."},
    {"Characters saved for your next mission.", "Personajes guardados para la próxima misión."},
    {"Could not save characters. Choices will last for this session only.", "No se pudieron guardar los personajes. La selección solo durará esta sesión."},
    {"Previous display settings restored.", "Ajustes de pantalla anteriores restaurados."},
    {"Settings saved.", "Ajustes guardados."},
    {"Could not save settings. Changes will last for this session only.", "No se pudieron guardar los ajustes. Los cambios solo durarán esta sesión."},
    {"Cannot apply these bindings. Check for duplicate or reserved keys.", "No se pueden aplicar las asignaciones. Revisa las teclas duplicadas o reservadas."},
    {"Player 2 controls applied. Resume to save this player's profile.", "Controles del jugador 2 aplicados. Reanuda para guardar su perfil."},
    {"Controls saved. Original profile settings save when you leave Options.", "Controles guardados. Los ajustes del perfil se guardan al salir de Opciones."},
    {"Could not save controls. Changes will last for this session only.", "No se pudieron guardar los controles. Los cambios solo durarán esta sesión."},
    {"That key is reserved. Choose another key.", "Esa tecla está reservada. Elige otra."},
    {"PLAYER ONE: CHARACTER UNAVAILABLE. USING ORIGINAL CHARACTER.", "JUGADOR 1: PERSONAJE NO DISPONIBLE. SE USA EL ORIGINAL."},
    {"PLAYER TWO: CHARACTER UNAVAILABLE. USING ORIGINAL CHARACTER.", "JUGADOR 2: PERSONAJE NO DISPONIBLE. SE USA EL ORIGINAL."},
    {"CHARACTERS UNAVAILABLE. USING ORIGINAL CHARACTERS.", "PERSONAJES NO DISPONIBLES. SE USAN LOS ORIGINALES."},
    {"%u x %u rendering", "Renderizado: %u x %u"},
    {"100% = original view. Zoom is preserved.", "100% = vista original. Conserva el zoom."},
    {"Changes gun and hand framing.", "Ajusta la vista del arma y las manos."},
    {"Level cutscenes only.", "Solo escenas dentro del nivel."},
    {"Active: %s - GPU support required", "Activo: %s - Requiere una GPU compatible"},
    {"HD menus, fonts and HUD.", "Menús, fuentes y HUD en HD."},
    {"100% = original. Lower is darker.", "100% = original. Menos es más oscuro."},
    {"Installed gameplay textures. UI unchanged.", "Texturas instaladas. No cambia la interfaz."},
    {"Install the HD texture pack in the launcher.", "Instala el paquete de texturas HD desde el lanzador."},
    {"Restart after changing aspect ratio.", "Reinicia tras cambiar la relación de aspecto."},
    {"Keep display settings? Reverting in %d seconds.", "¿Conservar ajustes? Se revierten en %d segundos."},
    {"Press ^pcStart", "Pulsa ^pcStart"},
    {"Press ^pcStart to Continue", "Pulsa ^pcStart para continuar"},
    {"Press any key to start", "Pulsa cualquier tecla para empezar"},
    {"Press any key to continue", "Pulsa cualquier tecla para continuar"},
    {"Preparing Shaders", "Preparando sombreadores"},
    {"Preparing shaders...", "Preparando sombreadores..."},
};
struct FoldLess {
    bool operator()(std::string_view a, std::string_view b) const {
        return std::lexicographical_compare(a.begin(), a.end(), b.begin(), b.end(), [](unsigned char x, unsigned char y) {
            return (x >= 'a' && x <= 'z' ? x - 32 : x) < (y >= 'a' && y <= 'z' ? y - 32 : y);
        });
    }
};
struct Entry {const char* host; std::string guest;};
const auto& Copies() {
    static const auto entries = [] {
        std::map<std::string_view, Entry, FoldLess> out;
        for (const auto& item : copy) {
            std::string guest;
            for (const auto* p = reinterpret_cast<const unsigned char*>(item.spanish); *p;) {
                unsigned c = *p++;
                if (c >= 0xC2 && c <= 0xC3 && (*p & 0xC0) == 0x80) c = ((c & 31) << 6) | (*p++ & 63);
                if (c >= 0xE0 && c <= 0xFC && c != 0xF7) c -= 32;
                guest += char(c);
            }
            out.emplace(item.english, Entry{item.spanish, std::move(guest)});
        }
        return out;
    }();
    return entries;
}
}
void Load(const void* table) {
    const auto* t = static_cast<const toml::table*>(table);
    requested = t && (*t)["language"]["text"].is_string() && (*t)["language"]["text"].value_or(std::string{}) == "es";
    enabled = false;
}
void Save(void* table) {
    if (auto* t = static_cast<toml::table*>(table)) t->insert_or_assign("language", toml::table{{"text", requested ? "es" : "en"}});
}
uint32_t NativeKey(std::string_view key) {
    uint32_t value = 0xFFFFFFFFu;
    for (unsigned char c : key) {
        if (c >= 'a' && c <= 'z') c -= 32;
        value ^= c;
        for (unsigned bit = 0; bit < 8; ++bit)
            value = (value >> 1) ^ (0xEDB88320u & (0u - (value & 1u)));
    }
    return ~value;
}
bool Initialize(const std::filesystem::path& directory) {
    enabled = false;
    catalogue.clear();
    if (!requested) return true;
    const auto path = directory / "language" / "es" / "language_text.bin";
    std::error_code error;
    const auto bytes = std::filesystem::file_size(path, error);
    if (error || bytes < 12 || bytes > (8u << 20)) return false;
    std::ifstream file(path, std::ios::binary);
    std::vector<char> data(size_t(bytes), 0);
    if (!file.read(data.data(), std::streamsize(data.size()))) return false;
    const bool legacy = std::memcmp(data.data(), "DWES0001", 8) == 0;
    // V2 hashed the source key's text, which is not available at native lookup.
    // Reject it rather than advertise a usable translation; the launcher repairs
    // the resource from its current pinned V3 payload without touching saves.
    if (!legacy && std::memcmp(data.data(), "DWES0003", 8)) return false;
    size_t position = 8;
    auto integer = [&](uint32_t& out) {
        if (position > data.size() || data.size() - position < 4) return false;
        const auto* p = reinterpret_cast<const unsigned char*>(data.data() + position);
        out = uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
        position += 4; return true;
    };
    auto string = [&](uint32_t size, std::string& out) {
        if (position > data.size() || size > data.size() - position) return false;
        out.assign(data.data() + position, size); position += size;
        return out.find('\0') == std::string::npos;
    };
    uint32_t count = 0;
    if (!integer(count) || !count || count > 20000) return false;
    Lines parsed;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t first, second, translated_size;
        if (!integer(first) || !integer(second) || !integer(translated_size) ||
            translated_size > 16384 || !translated_size) return false;
        uint64_t identity = uint64_t(first) | (uint64_t(second) << 32);
        std::string translated;
        if (legacy) {
            if (!first || first > 128 || second > 16384) return false;
            std::string key, original;
            if (!string(first, key) || !string(second, original)) return false;
            if (!std::all_of(key.begin(), key.end(), [](unsigned char c) {return c >= 32 && c < 127;})) return false;
            identity = ContextId(NativeKey(key), original);
        }
        if (!string(translated_size, translated)) return false;
        const auto [entry, inserted] = parsed.emplace(identity, translated);
        if (!inserted && entry->second != translated) return false;
    }
    if (position != data.size()) return false;
    catalogue = std::move(parsed);
    enabled = true;
    return true;
}
bool Spanish() {return enabled.load();}
const char* Text(const char* english) {
    if (!english || !Spanish()) return english;
    const auto& entries = Copies();
    const auto found = entries.find(english);
    return found == entries.end() ? english : found->second.host;
}
const char* Guest(const char* english) {
    if (!english || !Spanish()) return english;
    const auto& entries = Copies();
    const auto found = entries.find(english);
    return found == entries.end() ? english : found->second.guest.c_str();
}
std::string Translate(uint32_t key, std::string_view original) {
    if (!Spanish() || original.size() > 16384) return {};
    const auto found = catalogue.find(ContextId(key, original));
    return found == catalogue.end() ? std::string{} : found->second;
}
std::string Translate(std::string_view key, std::string_view original) {
    return key.size() > 128 ? std::string{} : Translate(NativeKey(key), original);
}
} // namespace darkwatch::language
