using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Microsoft.Win32;

#if !DIRECT_PLAY
[assembly: AssemblyTitle("Darkwatch: Darker Edition")]
[assembly: AssemblyProduct("Darkwatch: Darker Edition")]
[assembly: AssemblyVersion("0.6.1.0")]
[assembly: AssemblyFileVersion("0.6.1.0")]
[assembly: AssemblyInformationalVersion("0.6.1")]
#endif

namespace DarkwatchDarkerEdition
{
    public sealed class Launcher
    {
        public const string DiscImageFilter = "Xbox disc images (*.iso;*.xiso)|*.iso;*.xiso";
        public const string TexturePackFilter = "Darker Edition HD texture pack (*.zip;*.zip.001)|*.zip;*.zip.001";
        public const string SpanishPackFilter = "PS2 Darkwatch disc image (*.iso)|*.iso";
        readonly Window window;
        readonly string package = AppDomain.CurrentDomain.BaseDirectory;
        readonly string installRoot = SetupProcess.InstallRoot(AppDomain.CurrentDomain.BaseDirectory);
        readonly JavaScriptSerializer json = new JavaScriptSerializer();
        bool busy, installed, ready, closing, cancelRequested, hdTexturesInstalled, spanishInstalled, spanishAudioInstalled, updatingLanguage;
        string language = "en";
        string cancelFile, gameDirectory;
        readonly Action cancelPreparation;

        T Get<T>(string name) where T : FrameworkElement { return (T)window.FindName(name); }
        string Copy(string english, string spanish) { return language == "es" ? spanish : english; }
        public Window Window { get { return window; } }

        internal static string Localize(string message, string selectedLanguage)
        {
            if (selectedLanguage != "es" || String.IsNullOrEmpty(message)) return message;
            switch (message) {
                case "Import your own supported Darkwatch ISO to begin.": return "Importa tu propia ISO compatible de Darkwatch para empezar.";
                case "Installed. Files are verified before every launch.": return "Instalado. Los archivos se verifican antes de cada inicio.";
                case "All installed files verified.": return "Todos los archivos instalados están verificados.";
                case "Installed files verified": return "Archivos instalados verificados";
                case "Checking launcher files": return "Comprobando los archivos del lanzador";
                case "Preparing HD artwork from your disc": return "Preparando la interfaz HD a partir de tu disco";
                case "Preparing selectable characters...": return "Preparando los personajes seleccionables…";
                case "Preparing character resources...": return "Preparando los recursos de los personajes…";
                case "Preserving saves, controls, and shader cache": return "Conservando partidas, controles y caché de shaders";
                case "Copying prior launcher saves into this portable folder": return "Copiando las partidas anteriores a esta carpeta portátil";
                case "Shaders are ready": return "Shaders preparados";
                case "Verifying optional HD textures": return "Verificando las texturas HD opcionales";
                case "Installing optional HD textures": return "Instalando las texturas HD opcionales";
                case "Installing Spanish resources": return "Instalando los recursos en español";
                case "HD gameplay textures installed. Enable HD Textures in Graphics.": return "Texturas HD instaladas. Actívalas en Gráficos.";
                case "Spanish installed. Choose Español before starting the game.": return "Español instalado. Selecciona Español antes de iniciar el juego.";
                case "Spanish needs a supported PS2 ISO import. Import Spanish again or choose English; previous files are kept.": return "Importa de nuevo tu ISO compatible de PS2 o elige English. Se conservan los archivos anteriores.";
                case "Previous Spanish files were kept in the old installation. Import your PS2 ISO or choose English.": return "Se conserva el español anterior en la instalación antigua. Importa tu ISO de PS2 o elige English.";
                case "Darkwatch: Darker Edition is installed. Your original ISO was not changed.": return "Darkwatch: Darker Edition está instalado. Tu ISO original no se ha modificado.";
                case "Darkwatch: Darker Edition started.": return "Darkwatch: Darker Edition se ha iniciado.";
                case "Another setup or launch is already in progress.": return "Ya hay otra instalación o inicio en curso.";
                case "Close Darkwatch before installing, repairing, or starting another copy.": return "Cierra Darkwatch antes de instalar, reparar o iniciar otra copia.";
                case "This launcher package is incomplete or incompatible. Extract a fresh complete package.": return "El paquete del lanzador está incompleto o no es compatible. Extrae de nuevo el paquete completo.";
                case "Shader preparation made no progress for too long. Close other applications and try again.": return "La preparación de shaders lleva demasiado tiempo sin avanzar. Cierra otras aplicaciones e inténtalo de nuevo.";
                case "Shader preparation failed. Please try again.": return "Falló la preparación de shaders. Inténtalo de nuevo.";
                case "Shader preparation did not finish. Please try again.": return "No se completó la preparación de shaders. Inténtalo de nuevo.";
            }
            if (message.StartsWith("Verifying ", StringComparison.Ordinal)) return "Verificando " + message.Substring(10);
            if (message.StartsWith("Importing ", StringComparison.Ordinal)) return "Importando " + message.Substring(10);
            return Regex.Replace(message, @"^Preparing shaders — (\d+) of (\d+)$", "Preparando shaders — $1 de $2");
        }

#if LAUNCHER_TESTING
        public Launcher(bool preview = false) : this(preview, null)
#else
        public Launcher() : this(false, null)
#endif
        { }

        Launcher(bool preview, Action cancel)
        {
            cancelPreparation = cancel;
            var assembly = Assembly.GetExecutingAssembly();
            using (var stream = assembly.GetManifestResourceStream("Darkwatch.MainWindow.xaml"))
                window = (Window)XamlReader.Load(stream);
            var insignia = LoadImage("Darkwatch.Insignia.png");
            Get<Image>("Cover").Source = LoadImage("Darkwatch.Cover.png");
            Get<Image>("Insignia").Source = insignia;
            Get<Image>("SmallInsignia").Source = insignia;
            window.Icon = insignia;
            Get<Border>("TitleBar").MouseLeftButtonDown += delegate(object sender, MouseButtonEventArgs e) {
                if (e.OriginalSource is Button) return;
                if (e.LeftButton == MouseButtonState.Pressed) window.DragMove();
            };
            Get<Button>("MinimizeButton").Click += delegate { window.WindowState = WindowState.Minimized; };
            Get<Button>("CloseButton").Click += delegate { window.Close(); };
            Get<Button>("ImportButton").Click += async delegate {
                var dialog = new OpenFileDialog { Title = Copy("Select your original Xbox Darkwatch disc image", "Selecciona la imagen de tu disco original de Darkwatch para Xbox"), Filter = DiscImageFilter, CheckFileExists = true, Multiselect = false };
                if (dialog.ShowDialog(window) == true) await Run("--import-iso", dialog.FileName);
            };
            Get<Button>("TextureButton").Click += async delegate {
                var dialog = new OpenFileDialog { Title = Copy("Select the HD texture ZIP or its first part (.001)", "Selecciona el ZIP de texturas HD o su primera parte (.001)"), Filter = TexturePackFilter, CheckFileExists = true, Multiselect = false };
                if (dialog.ShowDialog(window) == true) await Run("--install-hd-textures", dialog.FileName);
            };
            Get<Button>("SpanishButton").Click += async delegate {
                var dialog = new OpenFileDialog { Title = Copy("Select your PS2 Darkwatch ISO (SLES-53564)", "Selecciona tu ISO de Darkwatch para PS2 (SLES-53564)"), Filter = SpanishPackFilter, CheckFileExists = true, Multiselect = false };
                if (dialog.ShowDialog(window) == true) await Run("--install-spanish", dialog.FileName);
            };
            Get<ComboBox>("LanguageChoice").SelectionChanged += async delegate {
                if (updatingLanguage || busy || !installed) return;
                var selected = Get<ComboBox>("LanguageChoice").SelectedItem as ComboBoxItem;
                string choice = selected == null ? null : selected.Tag as string;
                if (choice == language || (choice != "en" && choice != "es")) return;
                if (choice == "es" && !spanishInstalled) { SetButtons(); return; }
                await Run("--set-language", choice);
            };
            Get<Button>("VerifyButton").Click += async delegate { await Run("--verify", null); };
            Get<Button>("PlayButton").Click += async delegate { await Run("--play", null); };
            Get<Button>("CancelButton").Click += delegate { Cancel(); };
            Get<Button>("FolderButton").Click += delegate {
                try { Process.Start(new ProcessStartInfo { FileName = Directory.Exists(gameDirectory) ? gameDirectory : installRoot, UseShellExecute = true }); }
                catch (Exception ex) { Error(ex.Message); }
            };
            window.Closing += delegate(object sender, System.ComponentModel.CancelEventArgs e) {
                if (!busy) return;
                e.Cancel = true;
                if (cancelPreparation != null) { Cancel(); return; }
                if (MessageBox.Show(window, Copy("Cancel the current operation and close the launcher? Your existing installation will be kept.", "¿Cancelar la operación actual y cerrar el lanzador? Se conservará tu instalación."), "Darkwatch: Darker Edition", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) == MessageBoxResult.Yes) {
                    closing = true; Cancel();
                }
            };
            if (!preview && cancelPreparation == null)
                window.Loaded += async delegate { await Run("--status", null); };
            FitToWorkArea(SystemParameters.WorkArea);
            if (cancelPreparation != null) {
                busy = true;
                Get<Grid>("LaunchActions").Visibility = Visibility.Collapsed;
                Get<Grid>("RepairActions").Visibility = Visibility.Collapsed;
                Get<StackPanel>("TextureActions").Visibility = Visibility.Collapsed;
                Get<StackPanel>("LanguageActions").Visibility = Visibility.Collapsed;
            }
            SetButtons();
        }

        public static Launcher Preparing(Action cancel) { return new Launcher(false, cancel); }

        public void UpdatePreparation(Dictionary<string, object> item) { ApplyState(item); }

        public void FinishPreparation() { busy = false; window.Close(); }

        void FitToWorkArea(Rect area)
        {
            // WPF uses logical pixels; fit the complete interface at high desktop scaling.
            double scale = Math.Min(1, Math.Min(Math.Max(1, area.Width - 24) / 1060, Math.Max(1, area.Height - 24) / 720));
            window.Width = 1060 * scale; window.Height = 720 * scale;
        }

        static BitmapImage LoadImage(string name)
        {
            using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name)) {
                var image = new BitmapImage();
                image.BeginInit(); image.CacheOption = BitmapCacheOption.OnLoad; image.StreamSource = stream; image.EndInit(); image.Freeze();
                return image;
            }
        }

        void SetButtons()
        {
            Get<Button>("ImportButton").IsEnabled = !busy;
            Get<Button>("PlayButton").IsEnabled = !busy && ready;
            Get<Button>("VerifyButton").IsEnabled = !busy && installed;
            Get<Button>("FolderButton").IsEnabled = !busy && installed;
            Get<Button>("TextureButton").IsEnabled = !busy && ready;
            Get<Button>("TextureButton").Content = hdTexturesInstalled ? Copy("REINSTALL HD TEXTURES", "REINSTALAR TEXTURAS HD") : Copy("INSTALL HD TEXTURES", "INSTALAR TEXTURAS HD");
            Get<TextBlock>("TextureStatus").Text = hdTexturesInstalled
                ? Copy("Gameplay textures installed · Toggle in Graphics", "Texturas instaladas · Actívalas en Gráficos")
                : Copy("Optional download · Gameplay textures not installed", "Descarga opcional · Texturas del juego no instaladas");
            Get<Button>("SpanishButton").IsEnabled = !busy && ready;
            Get<Button>("SpanishButton").Content = Copy("INSTALL SPANISH", "INSTALAR ESPAÑOL");
            Get<ComboBox>("LanguageChoice").IsEnabled = !busy && installed;
            Get<ComboBoxItem>("SpanishChoice").IsEnabled = spanishInstalled;
            // Backend status refreshes must not start another language-change operation.
            updatingLanguage = true;
            try { Get<ComboBox>("LanguageChoice").SelectedIndex = language == "es" ? 1 : 0; }
            finally { updatingLanguage = false; }
            Get<TextBlock>("LanguageStatus").Text = spanishInstalled
                ? Copy("Game language · Spanish installed · Next launch", "Idioma del juego · Español instalado · Próximo inicio")
                : Copy("Game language · Spanish requires your PS2 ISO", "Idioma del juego · Español requiere tu ISO de PS2");
            System.Windows.Automation.AutomationProperties.SetName(Get<ComboBox>("LanguageChoice"), Copy("Game language", "Idioma del juego"));
            Get<ComboBox>("LanguageChoice").ToolTip = Copy("Choose English or installed Español, then start the game. Close the game before changing languages.", "Elige English o Español instalado e inicia el juego. Cierra el juego antes de cambiar de idioma.");
            Get<Button>("SpanishButton").ToolTip = Copy("Install Spanish text, subtitles and voices from your European PS2 Darkwatch ISO (SLES-53564). Import the Xbox game first. Your disc, saves and settings are kept.", "Instala textos, subtítulos y voces de tu ISO europea de Darkwatch para PS2 (SLES-53564). Importa primero el juego de Xbox. Se conservan tu disco, partidas y ajustes.");
            Get<Button>("CancelButton").Visibility = busy && (cancelFile != null || cancelPreparation != null) ? Visibility.Visible : Visibility.Collapsed;
            Get<Button>("CancelButton").IsEnabled = busy && !cancelRequested;
            Get<Button>("CancelButton").Content = Copy("CANCEL", "CANCELAR");
            Get<Button>("ImportButton").Content = installed ? Copy("IMPORT / REPAIR", "IMPORTAR / REPARAR") : Copy("IMPORT ISO", "IMPORTAR ISO");
            Get<Button>("PlayButton").Content = Copy("PLAY", "JUGAR");
            Get<Button>("VerifyButton").Content = Copy("VERIFY FILES", "VERIFICAR ARCHIVOS");
            Get<Button>("FolderButton").Content = Copy("OPEN GAME FOLDER", "ABRIR CARPETA DEL JUEGO");
            Get<Button>("MinimizeButton").ToolTip = Copy("Minimize", "Minimizar");
            Get<Button>("CloseButton").ToolTip = Copy("Close launcher", "Cerrar el lanzador");
            Get<Button>("TextureButton").ToolTip = Copy("Import your ISO first. Download all HD pack parts into one folder, then select the .001 file. A complete ZIP also works.", "Importa tu ISO primero. Descarga todas las partes HD en una carpeta y selecciona el archivo .001. También puedes usar el ZIP completo.");
            Get<TextBlock>("DiscTitle").Text = Copy("YOUR DISC, ENHANCED", "TU DISCO, MEJORADO");
            Get<TextBlock>("DiscFeatures").Text = Copy("Widescreen · HD interface · Mouse & keyboard", "Pantalla panorámica · Interfaz HD · Ratón y teclado");
            Get<TextBlock>("DiscNotice").Text = Copy("Original game files are not included.", "No se incluyen archivos del juego original.");
            Get<Button>("ImportButton").Background = (Brush)new BrushConverter().ConvertFromString(ready ? "#20232A" : "#701C25");
            Get<Button>("PlayButton").Background = (Brush)new BrushConverter().ConvertFromString(ready ? "#701C25" : "#20232A");
        }

        void ApplyState(Dictionary<string, object> item)
        {
            object value;
            if (item.TryGetValue("installed", out value)) installed = Convert.ToBoolean(value);
            if (item.TryGetValue("ready", out value)) ready = Convert.ToBoolean(value);
            if (item.TryGetValue("hd_textures_installed", out value)) hdTexturesInstalled = Convert.ToBoolean(value);
            if (item.TryGetValue("spanish_installed", out value)) spanishInstalled = Convert.ToBoolean(value);
            if (item.TryGetValue("spanish_audio_installed", out value)) spanishAudioInstalled = Convert.ToBoolean(value);
            if (item.TryGetValue("language", out value)) language = Object.Equals(value, "es") ? "es" : "en";
            if (!installed) { hdTexturesInstalled = false; spanishInstalled = false; spanishAudioInstalled = false; }
            if (item.TryGetValue("install_dir", out value)) gameDirectory = Convert.ToString(value);
            if (item.TryGetValue("message", out value)) Get<TextBlock>("StatusText").Text = Localize(Convert.ToString(value), language);
            if (item.TryGetValue("percent", out value) && value != null) {
                Get<ProgressBar>("Progress").IsIndeterminate = false;
                Get<ProgressBar>("Progress").Value = Math.Max(0, Math.Min(100, Convert.ToDouble(value)));
            }
            Get<TextBlock>("StateTitle").Text = ready ? Copy("THE NIGHT AWAITS", "LA NOCHE TE ESPERA") : Copy("PREPARE YOUR HUNT", "PREPARA TU CACERÍA");
            Get<TextBlock>("StateDescription").Text = ready
                ? Copy("Your copy is ready. Enter the hunt, or adjust your graphics and controls from the game’s Options menu.", "Tu copia está lista. Empieza la cacería o ajusta los gráficos y controles en las opciones del juego.")
                : Copy("Bring your own original Xbox Darkwatch ISO. Import it once to prepare Darker Edition on this PC.", "Necesitas tu propia ISO original de Darkwatch para Xbox. Impórtala para preparar Darker Edition en este PC.");
            object kind;
            if (cancelPreparation != null || (item.TryGetValue("event", out kind) && Object.Equals(kind, "shader_prepare"))) {
                Get<TextBlock>("StateTitle").Text = Copy("PREPARING SHADERS", "PREPARANDO SHADERS");
                Get<TextBlock>("StateDescription").Text = Copy("Preparing Darkwatch’s graphics before the hunt. This only runs when shaders need preparation. Prepared shaders are reused on later launches.", "Preparando los gráficos de Darkwatch antes de la cacería. Solo se realiza cuando es necesario. Los shaders preparados se reutilizan en las siguientes partidas.");
            }
            if (cancelRequested && item.TryGetValue("event", out kind) &&
                (Object.Equals(kind, "progress") || Object.Equals(kind, "shader_prepare")))
                Get<TextBlock>("StatusText").Text = Copy("Canceling safely…", "Cancelando de forma segura…");
            SetButtons();
        }

        void Error(string message)
        {
            Get<TextBlock>("StatusText").Text = Localize(message, language);
            Get<TextBlock>("StatusText").Foreground = new SolidColorBrush(Color.FromRgb(229, 153, 139));
        }

        void Cancel()
        {
            if (cancelPreparation != null) {
                try {
                    cancelPreparation();
                    cancelRequested = true;
                    Get<TextBlock>("StatusText").Text = Copy("Canceling safely…", "Cancelando de forma segura…");
                    Get<Button>("CancelButton").IsEnabled = false;
                } catch (Exception ex) { Error(Copy("Could not request cancellation: ", "No se pudo solicitar la cancelación: ") + ex.Message); }
                return;
            }
            if (cancelFile == null) return;
            try {
                File.WriteAllText(cancelFile, "cancel");
                cancelRequested = true;
                Get<TextBlock>("StatusText").Text = Copy("Canceling safely…", "Cancelando de forma segura…");
                Get<Button>("CancelButton").IsEnabled = false;
            } catch (Exception ex) { Error(Copy("Could not request cancellation: ", "No se pudo solicitar la cancelación: ") + ex.Message); closing = false; }
        }

        async Task Run(string action, string argument)
        {
            if (busy) return;
            busy = true; cancelRequested = false;
            bool failed = false;
            Get<TextBlock>("StatusText").Foreground = new SolidColorBrush(Color.FromRgb(184, 183, 181));
            Get<TextBlock>("StatusText").Text = action == "--play" ? Copy("Verifying your copy before launch…", "Verificando tu copia antes de iniciar…")
                : action == "--import-iso" ? Copy("Checking your disc image…", "Comprobando la imagen del disco…")
                : action == "--install-hd-textures" ? Copy("Checking your HD texture pack…", "Comprobando el paquete de texturas HD…")
                : action == "--install-spanish" ? Copy("Checking your PS2 disc…", "Comprobando tu disco de PS2…")
                : action == "--set-language" ? Copy("Changing language…", "Cambiando el idioma…")
                : Copy("Checking installation…", "Comprobando la instalación…");
            Get<ProgressBar>("Progress").Value = 0;
            Get<ProgressBar>("Progress").IsIndeterminate = true;
            try {
                // A private per-job token cannot cancel another open launcher's operation.
                if (action != "--status") Directory.CreateDirectory(installRoot);
                cancelFile = action == "--status" ? null : Path.Combine(installRoot, ".cancel-" + Guid.NewGuid().ToString("N"));
                var info = SetupProcess.Create(package, installRoot, action, argument, cancelFile);
                SetButtons();
                string errorText = "";
                int code = await Task.Run(() => {
                    using (var process = new Process { StartInfo = info }) {
                        if (!process.Start()) throw new IOException(Copy("The setup helper could not start.", "No se pudo iniciar el asistente de instalación."));
                        var errors = process.StandardError.ReadToEndAsync();
                        string line;
                        while ((line = process.StandardOutput.ReadLine()) != null) {
                            Dictionary<string, object> item;
                            try { item = json.Deserialize<Dictionary<string, object>>(line); }
                            catch (ArgumentException) { continue; }
                            if (item == null) continue;
                            window.Dispatcher.Invoke(new Action(() => ApplyState(item)));
                        }
                        process.WaitForExit(); errorText = errors.Result;
                        return process.ExitCode;
                    }
                });
                failed = code != 0;
                if (failed) {
                    if (!String.IsNullOrWhiteSpace(errorText)) Error(errorText.Length > 500 ? errorText.Substring(0, 500) : errorText);
                    else Error(Get<TextBlock>("StatusText").Text);
                }
            } catch (Exception ex) { failed = true; Error(ex.Message); }
            finally {
                try { if (cancelFile != null && File.Exists(cancelFile)) File.Delete(cancelFile); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
                cancelFile = null; busy = false; cancelRequested = false;
                Get<ProgressBar>("Progress").IsIndeterminate = false;
                SetButtons();
                if (closing) window.Close();
            }
            if (!failed && action == "--play") window.WindowState = WindowState.Minimized;
        }

#if LAUNCHER_TESTING
        public void RenderPreview(string path, string state)
        {
            if (state == "spanish-ready") ApplyState(new Dictionary<string, object> { { "installed", true }, { "ready", true }, { "hd_textures_installed", true }, { "spanish_installed", true }, { "language", "es" }, { "message", "Instalación verificada. Todo listo para jugar." }, { "percent", 100 } });
            else if (state == "spanish-shaders") ApplyState(new Dictionary<string, object> { { "event", "shader_prepare" }, { "language", "es" }, { "message", "Preparando shaders — 2.220 de 4.440" }, { "percent", 50 } });
            else if (state == "ready" || state == "hd-installed") ApplyState(new Dictionary<string, object> { { "installed", true }, { "ready", true }, { "hd_textures_installed", state == "hd-installed" }, { "message", "Installation verified. Ready to play." }, { "percent", 100 } });
            else if (state == "shaders") ApplyState(new Dictionary<string, object> { { "event", "shader_prepare" }, { "message", "Preparing shaders — 2,220 of 4,440" }, { "percent", 50 } });
            else if (state == "importing") {
                busy = true; cancelFile = "preview";
                ApplyState(new Dictionary<string, object> { { "message", "Preparing HD menus and HUD…" }, { "percent", 78 } });
            } else Get<TextBlock>("StatusText").Text = "Choose your ISO to begin. Your original file stays untouched.";
            // Render the actual content without creating or showing a desktop window.
            var content = (FrameworkElement)window.Content; window.Content = null;
            content.Resources = window.Resources;
            content.SetValue(System.Windows.Documents.TextElement.ForegroundProperty, window.Foreground);
            content.SetValue(System.Windows.Documents.TextElement.FontFamilyProperty, window.FontFamily);
            content.Measure(new Size(window.Width, window.Height));
            content.Arrange(new Rect(0, 0, window.Width, window.Height)); content.UpdateLayout();
            var render = new RenderTargetBitmap((int)window.Width, (int)window.Height, 96, 96, PixelFormats.Pbgra32);
            render.Render(content);
            var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(render));
            using (var output = File.Create(path)) encoder.Save(output);
        }
#endif

#if !DIRECT_PLAY
        [STAThread]
        public static int Main(string[] args)
        {
            try {
                var app = new Application();
                var launcher = new Launcher();
                return app.Run(launcher.Window);
            } catch (Exception ex) {
                MessageBox.Show(ex.Message, "Darkwatch: Darker Edition", MessageBoxButton.OK, MessageBoxImage.Error); return 1;
            }
        }
#endif
    }
}
