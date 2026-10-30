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
[assembly: AssemblyVersion("0.7.0.0")]
[assembly: AssemblyFileVersion("0.7.0.0")]
[assembly: AssemblyInformationalVersion("0.7")]
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
        bool busy, installed, ready, updateAvailable, closing, cancelRequested, hdTexturesInstalled, spanishInstalled, spanishAudioInstalled, updatingLanguage;
        string language = "en", sourceMode = "extracted";
        string cancelFile, gameDirectory;
        readonly Action cancelPreparation;
        bool checkingRelease, startupStarted, windowClosed, completeUpdate, manageOpen, sourceOpen, releaseRequested, freshStatus;
        string releaseStatus = "idle", latestRelease, releaseUrl;

        T Get<T>(string name) where T : FrameworkElement { return (T)window.FindName(name); }
        string Copy(string english, string spanish) { return language == "es" ? spanish : english; }
        public Window Window { get { return window; } }

        internal static string Localize(string message, string selectedLanguage)
        {
            if (selectedLanguage != "es" || String.IsNullOrEmpty(message)) return message;
            switch (message) {
                case "Import your own supported Darkwatch ISO to begin.": return "Importa tu propia ISO compatible de Darkwatch para empezar.";
                case "Import once, or select Use Existing Install to reuse a previous installation without the ISO.": return "Importa una vez o elige Usar instalación existente para reutilizar una instalación anterior sin la ISO.";
                case "Select Game to use your Xbox ISO directly, import it once, or reuse an existing installation.": return "Elige Seleccionar juego para usar tu ISO de Xbox directamente, importarla una vez o reutilizar una instalación existente.";
                case "The game ISO is unavailable. Reconnect its drive or select its new location with Use ISO directly.": return "La ISO del juego no está disponible. Conecta su unidad o selecciona su nueva ubicación en Usar ISO directamente.";
                case "The game ISO changed. Select it again with Use ISO directly to verify it; your saves are kept.": return "La ISO del juego ha cambiado. Selecciónala de nuevo en Usar ISO directamente para verificarla; se conservan tus partidas.";
                case "The ISO source record needs repair. Select your ISO again with Use ISO directly.": return "El registro de la ISO necesita reparación. Selecciónala de nuevo en Usar ISO directamente.";
                case "The ISO source record differs. Select your ISO again with Use ISO directly.": return "El registro de la ISO no coincide. Selecciónala de nuevo en Usar ISO directamente.";
                case "Update available. Your retained ISO, prepared game data, saves and add-ons will be reused.": return "Hay una actualización. Se reutilizarán tu ISO, los archivos preparados, las partidas y los complementos.";
                case "Game updated. Your ISO, prepared resources, saves, settings and add-ons were reused.": return "Juego actualizado. Se reutilizaron tu ISO, los recursos preparados, las partidas, los ajustes y los complementos.";
                case "Darkwatch is ready. Keep the selected ISO available; only prepared resources were copied.": return "Darkwatch está listo. Conserva la ISO seleccionada; solo se han copiado los recursos preparados.";
                case "Update available. Choose Update Game; your installed data, saves and add-ons will be reused without the ISO.": return "Hay una actualización. Elige Actualizar juego para reutilizar tus archivos, partidas y complementos sin la ISO.";
                case "This older installation needs one final ISO import for the content update. Future updates will reuse its installed data; saves and settings are kept.": return "Esta instalación antigua necesita importar la ISO una última vez. Las siguientes actualizaciones reutilizarán sus archivos; se conservan partidas y ajustes.";
                case "Game updated. Your installed data, saves, settings and add-ons were reused; no ISO was needed.": return "Juego actualizado. Se reutilizaron tus archivos, partidas, ajustes y complementos sin necesitar la ISO.";
                case "Checking installed game data for update": return "Comprobando los archivos instalados para actualizar";
                case "Preparing update from installed game data": return "Preparando la actualización desde los archivos instalados";
                case "Updating HD interface": return "Actualizando la interfaz HD";
                case "Applying update; saves and add-ons stay in place": return "Aplicando la actualización; se conservan las partidas y los complementos";
                case "The saved installation location is invalid. Select your existing installation again.": return "La ubicación guardada de la instalación no es válida. Selecciona de nuevo tu instalación existente.";
                case "Select the original GameData folder, not another linked launcher.":
                case "Choose the original GameData folder, not another linked launcher.": return "Selecciona la carpeta GameData original, no otro lanzador vinculado.";
                case "Choose the previous Darkwatch folder or its GameData folder.": return "Selecciona la carpeta anterior de Darkwatch o su carpeta GameData.";
                case "The selected installation uses a different disc revision.": return "La instalación seleccionada usa una versión diferente del disco.";
                case "The selected installation is incomplete. Keep its saves and repair it from your disc.": return "La instalación seleccionada está incompleta. Conserva sus partidas y repárala desde tu disco.";
                case "Choose Use Existing Install or import your Xbox ISO once.": return "Elige Usar instalación existente o importa tu ISO de Xbox una vez.";
                case "The installed disc revision does not match this update.": return "La versión del disco instalado no es compatible con esta actualización.";
                case "This installation needs the character content update. Choose Update Game in the launcher.": return "Esta instalación necesita actualizar los personajes. Elige Actualizar juego en el lanzador.";
                case "Updated character data failed verification; no installed files were changed.": return "Los personajes actualizados no superaron la verificación. No se modificó ningún archivo instalado.";
                case "Runtime changed during update; no installed files were changed.": return "El ejecutable cambió durante la actualización. No se modificó ningún archivo instalado.";
                case "Checking the latest official release...": return "Comprobando la última versión oficial…";
                case "Downloading the new release...": return "Descargando la nueva versión…";
                case "Extracting the verified release...": return "Extrayendo la versión verificada…";
                case "Verifying every new release file...": return "Verificando todos los archivos de la nueva versión…";
                case "The new release is verified and ready to apply.": return "La nueva versión está verificada y lista para instalar.";
                case "Download verified. Restarting the launcher to apply the update.": return "Descarga verificada. Reiniciando el lanzador para instalar la actualización.";
                case "A launcher update is in progress. Close and reopen the launcher to finish recovery before playing or installing.": return "Hay una actualización del lanzador en curso. Ciérralo y vuelve a abrirlo para completar la recuperación antes de jugar o instalar.";
                case "A previous update needs recovery. Restart the launcher first.": return "Es necesario recuperar una actualización anterior. Reinicia primero el lanzador.";
                case "Start the update using the launcher Update button.": return "Inicia la actualización con el botón de actualización del lanzador.";
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
            Get<Button>("ManageButton").Click += delegate { ShowManage(true); };
            Get<Button>("BackButton").Click += delegate { ShowManage(false); };
            window.PreviewKeyDown += delegate(object sender, KeyEventArgs e) {
                if (e.Key != Key.Escape) return;
                if (Get<ComboBox>("LanguageChoice").IsDropDownOpen) {
                    Get<ComboBox>("LanguageChoice").IsDropDownOpen = false; e.Handled = true;
                } else if (sourceOpen && !busy) { ShowSource(false); e.Handled = true; }
                else if (manageOpen && !busy) { ShowManage(false); e.Handled = true; }
            };
            Get<Button>("CheckUpdatesButton").Click += async delegate {
                if (busy || checkingRelease) return;
                releaseRequested = true; await CheckForUpdates();
            };
            Get<Button>("ReleaseButton").Click += async delegate {
                if (busy || checkingRelease || releaseStatus != "available") return;
                if (!ValidReleaseUrl(releaseUrl, latestRelease)) {
                    releaseStatus = "unavailable"; releaseUrl = null; SetReleaseStatus(); return;
                }
                await Run("--download-update", null);
            };
            Get<Button>("ImportButton").Click += async delegate {
                if (installed && updateAvailable) await Run("--update", null);
                else ShowSource(true);
            };
            Get<Button>("RepairIsoButton").Click += delegate { ShowSource(true); };
            Get<Button>("SourceBackButton").Click += delegate { ShowSource(false); };
            Get<Button>("UseIsoButton").Click += async delegate { await SelectIso("--use-iso"); };
            Get<Button>("ExtractIsoButton").Click += async delegate { await SelectIso("--import-iso"); };
            Get<Button>("ExistingInstallButton").Click += async delegate { await UseExistingInstall(); };
            Get<Button>("HomeExistingButton").Click += async delegate { await UseExistingInstall(); };
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
            window.Closed += delegate { windowClosed = true; };
            if (!preview && cancelPreparation == null)
                window.Loaded += async delegate { await Startup(); };
            FitToWorkArea(SystemParameters.WorkArea);
            if (cancelPreparation != null) busy = true;
            SetButtons();
        }

        void ShowManage(bool show)
        {
            if (busy || cancelPreparation != null) return;
            manageOpen = show;
            SetButtons();
            Get<Button>(show ? "BackButton" : "ManageButton").Focus();
        }

        void ShowSource(bool show)
        {
            if (busy || cancelPreparation != null) return;
            sourceOpen = show;
            SetButtons();
            Get<Button>(show ? "SourceBackButton" : manageOpen ? "RepairIsoButton" : "ImportButton").Focus();
        }

        async Task UseExistingInstall()
        {
            using (var dialog = new System.Windows.Forms.FolderBrowserDialog {
                Description = Copy("Select your previous Darkwatch folder or its GameData folder. Files stay in that folder.", "Selecciona la carpeta anterior de Darkwatch o su carpeta GameData. Los archivos permanecerán allí."),
                ShowNewFolderButton = false
            }) {
                if (dialog.ShowDialog(new FolderDialogOwner(window)) == System.Windows.Forms.DialogResult.OK)
                    await Run("--use-installation", dialog.SelectedPath);
            }
        }

        public static Launcher Preparing(Action cancel) { return new Launcher(false, cancel); }

        public void UpdatePreparation(Dictionary<string, object> item) { ApplyState(item); }

        public void FinishPreparation() { busy = false; window.Close(); }

        async Task Startup()
        {
            if (startupStarted || cancelPreparation != null || windowClosed) return;
            startupStarted = true;
            Task releaseCheck = CheckForUpdates();
            await Run("--status", null);
            if (freshStatus && !windowClosed && !installed) await DetectAssetsIso();
            if (completeUpdate && !windowClosed && installed && updateAvailable) await Run("--update", null);
            await releaseCheck;
        }

        async Task DetectAssetsIso()
        {
            try {
                string assets = Path.Combine(package, "assets");
                if (!Directory.Exists(assets)) return;
                string candidate = null;
                foreach (string path in Directory.EnumerateFiles(assets)) {
                    string extension = Path.GetExtension(path);
                    if (!String.Equals(extension, ".iso", StringComparison.OrdinalIgnoreCase) &&
                        !String.Equals(extension, ".xiso", StringComparison.OrdinalIgnoreCase)) continue;
                    if (candidate != null) {
                        ShowSource(true);
                        Get<TextBlock>("StatusText").Text = Copy(
                            "Several disc images are in assets. Select the Xbox ISO you want to use.",
                            "Hay varias imágenes de disco en assets. Selecciona la ISO de Xbox que quieres usar.");
                        return;
                    }
                    candidate = path;
                }
                if (candidate == null) return;
                // The normal backend authenticates the disc, prepares only the
                // required resources, and retains cancellation/rollback behavior.
                // Keep the chooser visible if it rejects an unsupported image.
                ShowSource(true);
                await Run("--use-iso", candidate);
            } catch (IOException ex) { Error(ex.Message); }
            catch (UnauthorizedAccessException ex) { Error(ex.Message); }
        }

        internal static bool ValidReleaseUrl(string url, string version)
        {
            return version != null && version.Length <= 40 &&
                Regex.IsMatch(version, @"\A[0-9]+(?:\.[0-9]+){1,3}\z") &&
                String.Equals(url, "https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v" + version, StringComparison.Ordinal);
        }

        void SetReleaseStatus()
        {
            Get<Grid>("ReleaseActions").Visibility = cancelPreparation == null && !busy && releaseStatus == "available" ? Visibility.Visible : Visibility.Collapsed;
            Get<TextBlock>("ReleaseStatus").Visibility = cancelPreparation == null && !busy && (releaseStatus == "available" || releaseRequested || manageOpen) ? Visibility.Visible : Visibility.Collapsed;
            Get<Button>("ReleaseButton").IsEnabled = !checkingRelease && !busy;
            Get<Button>("ReleaseButton").Content = Copy("INSTALL UPDATE", "INSTALAR ACTUALIZACIÓN");
            Get<Button>("ReleaseButton").ToolTip = Copy("Download this release and update the current folder. Your game data, saves and settings are kept. The launcher restarts to finish.", "Descarga esta versión y actualiza la carpeta actual. Se conservan tus archivos, partidas y ajustes. El lanzador se reiniciará para terminar.");
            Get<Button>("CheckUpdatesButton").IsEnabled = !checkingRelease && !busy;
            Get<Button>("CheckUpdatesButton").Content = checkingRelease ? Copy("CHECKING…", "BUSCANDO…") : Copy("CHECK FOR UPDATES", "BUSCAR ACTUALIZACIONES");
            Get<Button>("CheckUpdatesButton").ToolTip = Copy("Check GitHub for a newer Windows release. This does not change your installation.", "Busca una versión más reciente para Windows en GitHub. No modifica tu instalación.");
            Get<TextBlock>("ReleaseStatus").Text = checkingRelease ? Copy("Checking for updates…", "Buscando actualizaciones…")
                : releaseStatus == "available" ? Copy("Version " + latestRelease + " available", "Versión " + latestRelease + " disponible")
                : releaseStatus == "current" ? Copy("No newer release", "No hay versión más reciente")
                : releaseStatus == "unavailable" ? Copy("Could not check for updates", "No se pudo comprobar")
                : Copy("Check GitHub for updates", "Buscar actualizaciones en GitHub");
        }

        async Task CheckForUpdates()
        {
            if (checkingRelease || cancelPreparation != null || windowClosed) return;
            checkingRelease = true;
            SetReleaseStatus();
            Dictionary<string, object> result = null;
            try {
                // Release discovery has no installation lock, progress, or cancellation token.
                var info = SetupProcess.Create(package, installRoot, "--check-updates");
                result = await Task.Run(() => {
                    using (var process = new Process { StartInfo = info }) {
                        if (!process.Start()) return null;
                        var output = process.StandardOutput.ReadToEndAsync();
                        var errors = process.StandardError.ReadToEndAsync();
                        if (!process.WaitForExit(15000)) { process.Kill(); process.WaitForExit(); return null; }
                        if (process.ExitCode != 0) return null;
                        errors.GetAwaiter().GetResult();
                        using (var lines = new StringReader(output.GetAwaiter().GetResult())) {
                            string line;
                            while ((line = lines.ReadLine()) != null) {
                                Dictionary<string, object> item;
                                try { item = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(line); }
                                catch (ArgumentException) { continue; }
                                object kind;
                                if (item != null && item.TryGetValue("event", out kind) && Object.Equals(kind, "release_check")) return item;
                            }
                        }
                        return null;
                    }
                });
            } catch (Exception) { }
            finally { checkingRelease = false; }
            if (windowClosed) return;
            releaseStatus = "unavailable"; releaseUrl = null; latestRelease = null;
            object status, version, url;
            if (result != null && result.TryGetValue("status", out status)) {
                if (Object.Equals(status, "current")) releaseStatus = "current";
                else if (Object.Equals(status, "available") && result.TryGetValue("latest_version", out version) &&
                         result.TryGetValue("release_url", out url) && ValidReleaseUrl(url as string, version as string)) {
                    releaseStatus = "available"; latestRelease = (string)version; releaseUrl = (string)url;
                }
            }
            SetReleaseStatus();
        }

        sealed class FolderDialogOwner : System.Windows.Forms.IWin32Window
        {
            public IntPtr Handle { get; private set; }
            public FolderDialogOwner(Window owner) { Handle = new System.Windows.Interop.WindowInteropHelper(owner).Handle; }
        }

        async Task SelectIso(string action)
        {
            var dialog = new OpenFileDialog { Title = Copy("Select your original Xbox Darkwatch disc image", "Selecciona la imagen de tu disco original de Darkwatch para Xbox"), Filter = DiscImageFilter, CheckFileExists = true, Multiselect = false };
            if (dialog.ShowDialog(window) == true) await Run(action, dialog.FileName);
        }

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
            bool idle = !busy && cancelPreparation == null;
            bool showManage = idle && manageOpen && !sourceOpen;
            bool showSource = idle && sourceOpen;
            Get<StackPanel>("HomePanel").Visibility = showManage || showSource ? Visibility.Collapsed : Visibility.Visible;
            Get<StackPanel>("ManagePanel").Visibility = showManage ? Visibility.Visible : Visibility.Collapsed;
            Get<StackPanel>("SourcePanel").Visibility = showSource ? Visibility.Visible : Visibility.Collapsed;
            Get<Grid>("LaunchActions").Visibility = idle ? Visibility.Visible : Visibility.Collapsed;
            Get<Button>("ManageButton").Visibility = idle ? Visibility.Visible : Visibility.Collapsed;
            Get<Button>("ImportButton").Visibility = ready ? Visibility.Collapsed : Visibility.Visible;
            Get<Button>("PlayButton").Visibility = ready ? Visibility.Visible : Visibility.Collapsed;
            Get<ProgressBar>("Progress").Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
            Get<Button>("ManageButton").Content = Copy("MANAGE", "ADMINISTRAR");
            Get<Button>("ManageButton").ToolTip = Copy("Game files, HD textures, language and updates", "Archivos del juego, texturas HD, idioma y actualizaciones");
            Get<Button>("BackButton").Content = Copy("← BACK", "← VOLVER");
            Get<TextBlock>("ManageTitle").Text = Copy("MANAGE GAME", "ADMINISTRAR JUEGO");
            Get<TextBlock>("FilesTitle").Text = Copy("GAME FILES", "ARCHIVOS DEL JUEGO");
            Get<TextBlock>("ContentTitle").Text = Copy("TEXTURES & LANGUAGE", "TEXTURAS E IDIOMA");
            Get<Button>("ImportButton").IsEnabled = !busy;
            Get<Button>("HomeExistingButton").IsEnabled = !busy;
            Get<Button>("UseIsoButton").IsEnabled = !busy;
            Get<Button>("ExtractIsoButton").IsEnabled = !busy;
            Get<Button>("ExistingInstallButton").IsEnabled = !busy;
            Get<Button>("RepairIsoButton").IsEnabled = !busy;
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
            Get<Button>("SpanishButton").ToolTip = Copy("Install Spanish text, subtitles and voices from your European PS2 Darkwatch ISO (SLES-53564). Set up the Xbox game first. Your disc, saves and settings are kept.", "Instala textos, subtítulos y voces de tu ISO europea de Darkwatch para PS2 (SLES-53564). Prepara primero el juego de Xbox. Se conservan tu disco, partidas y ajustes.");
            Get<Button>("CancelButton").Visibility = busy && (cancelFile != null || cancelPreparation != null) ? Visibility.Visible : Visibility.Collapsed;
            Get<Button>("CancelButton").IsEnabled = busy && !cancelRequested;
            Get<Button>("CancelButton").Content = Copy("CANCEL", "CANCELAR");
            bool needsUpdate = installed && updateAvailable;
            Get<Button>("ImportButton").Content = needsUpdate ? Copy("UPDATE GAME", "ACTUALIZAR JUEGO") : Copy("SELECT GAME", "SELECCIONAR JUEGO");
            Get<TextBlock>("SourceTitle").Text = Copy("SELECT GAME", "SELECCIONAR JUEGO");
            Get<Button>("SourceBackButton").Content = Copy("← BACK", "← VOLVER");
            Get<Button>("UseIsoButton").Content = Copy("USE ISO DIRECTLY", "USAR ISO DIRECTAMENTE");
            Get<Button>("ExtractIsoButton").Content = Copy("IMPORT ONCE", "IMPORTAR UNA VEZ");
            Get<TextBlock>("UseIsoHint").Text = Copy("Play from your Xbox ISO. Keep the ISO in place for future launches.", "Juega desde tu ISO de Xbox. Consérvala en su ubicación para iniciar el juego.");
            Get<TextBlock>("ExtractIsoHint").Text = Copy("Copy the game files once. The ISO can be removed after setup.", "Copia los archivos del juego una vez. Puedes eliminar la ISO después de la instalación.");
            Get<TextBlock>("ExistingHint").Text = Copy("Reuse game files, saves and add-ons from a previous installation.", "Reutiliza los archivos, partidas y complementos de una instalación anterior.");
            Get<Button>("ExistingInstallButton").Content = Copy("USE EXISTING INSTALL", "USAR INSTALACIÓN EXISTENTE");
            Get<Button>("ExistingInstallButton").ToolTip = Copy("Select a previous Darkwatch folder or GameData. Reuse its game files, saves and settings in place without importing your ISO again.", "Selecciona una carpeta anterior de Darkwatch o GameData. Reutiliza sus archivos, partidas y ajustes sin copiarlos ni importar de nuevo tu ISO.");
            Get<Button>("HomeExistingButton").Content = Get<Button>("ExistingInstallButton").Content;
            Get<Button>("HomeExistingButton").ToolTip = Get<Button>("ExistingInstallButton").ToolTip;
            Get<Button>("RepairIsoButton").Content = Copy("SELECT GAME", "SELECCIONAR JUEGO");
            Get<Button>("PlayButton").Content = Copy("PLAY", "JUGAR");
            Get<Button>("VerifyButton").Content = Copy("VERIFY FILES", "VERIFICAR ARCHIVOS");
            Get<Button>("FolderButton").Content = Copy("OPEN GAME FOLDER", "ABRIR CARPETA DEL JUEGO");
            Get<Button>("MinimizeButton").ToolTip = Copy("Minimize", "Minimizar");
            Get<Button>("CloseButton").ToolTip = Copy("Close launcher", "Cerrar el lanzador");
            Get<Button>("TextureButton").ToolTip = Copy("Set up your game first. Download all HD pack parts into one folder, then select the .001 file. A complete ZIP also works.", "Prepara tu juego primero. Descarga todas las partes HD en una carpeta y selecciona el archivo .001. También puedes usar el ZIP completo.");
            Get<Button>("ImportButton").Background = (Brush)new BrushConverter().ConvertFromString(ready ? "#20232A" : "#701C25");
            Get<Button>("PlayButton").Background = (Brush)new BrushConverter().ConvertFromString(ready ? "#701C25" : "#20232A");
            SetReleaseStatus();
        }

        void ApplyState(Dictionary<string, object> item)
        {
            object value;
            object kind, statusInstalled;
            if (item.TryGetValue("event", out kind) && Object.Equals(kind, "status"))
                freshStatus = item.TryGetValue("installed", out statusInstalled) && Object.Equals(statusInstalled, false);
            if (item.TryGetValue("installed", out value)) installed = Convert.ToBoolean(value);
            if (item.TryGetValue("ready", out value)) ready = Convert.ToBoolean(value);
            if (item.TryGetValue("update_available", out value)) updateAvailable = Convert.ToBoolean(value);
            if (item.TryGetValue("hd_textures_installed", out value)) hdTexturesInstalled = Convert.ToBoolean(value);
            if (item.TryGetValue("spanish_installed", out value)) spanishInstalled = Convert.ToBoolean(value);
            if (item.TryGetValue("spanish_audio_installed", out value)) spanishAudioInstalled = Convert.ToBoolean(value);
            if (item.TryGetValue("language", out value)) language = Object.Equals(value, "es") ? "es" : "en";
            if (item.TryGetValue("source_mode", out value)) sourceMode = Object.Equals(value, "iso") ? "iso" : "extracted";
            if (!installed) { updateAvailable = false; hdTexturesInstalled = false; spanishInstalled = false; spanishAudioInstalled = false; }
            if (item.TryGetValue("install_dir", out value)) gameDirectory = Convert.ToString(value);
            if (item.TryGetValue("message", out value)) Get<TextBlock>("StatusText").Text = Localize(Convert.ToString(value), language);
            if (item.TryGetValue("percent", out value) && value != null) {
                Get<ProgressBar>("Progress").IsIndeterminate = false;
                Get<ProgressBar>("Progress").Value = Math.Max(0, Math.Min(100, Convert.ToDouble(value)));
            }
            Get<TextBlock>("StateTitle").Text = ready ? Copy("THE NIGHT AWAITS", "LA NOCHE TE ESPERA") : Copy("PREPARE YOUR HUNT", "PREPARA TU CACERÍA");
            Get<TextBlock>("StateDescription").Text = ready
                ? sourceMode == "iso" ? Copy("Ready to play from your ISO. Keep it in place for future launches.", "Listo para jugar desde tu ISO. Consérvala en su ubicación para iniciar el juego.")
                : Copy("Your copy is ready. Enter the hunt.", "Tu copia está lista. Empieza la cacería.")
                : installed && updateAvailable
                ? Copy("Update your installed copy for this release. Your game files, saves and settings stay in the same location.", "Actualiza tu copia instalada para esta versión. Tus archivos, partidas y ajustes permanecen en la misma ubicación.")
                : installed
                ? Copy("Your installation needs attention. Verify files in Manage, or select your Xbox ISO again.", "Tu instalación requiere atención. Verifica los archivos en Administrar o selecciona de nuevo tu ISO de Xbox.")
                : Copy("Put your Xbox ISO in assets and restart, or choose Select Game.", "Pon tu ISO de Xbox en assets y reinicia, o elige Seleccionar juego.");
            item.TryGetValue("event", out kind);
            if (Object.Equals(kind, "shader_prepare")) {
                Get<TextBlock>("StateTitle").Text = Copy("PREPARING SHADERS", "PREPARANDO SHADERS");
                Get<TextBlock>("StateDescription").Text = Copy("Preparing Darkwatch’s graphics before the hunt. This only runs when shaders need preparation. Prepared shaders are reused on later launches.", "Preparando los gráficos de Darkwatch antes de la cacería. Solo se realiza cuando es necesario. Los shaders preparados se reutilizan en las siguientes partidas.");
            } else if (cancelPreparation != null) {
                Get<TextBlock>("StateTitle").Text = Copy("PREPARING YOUR GAME", "PREPARANDO EL JUEGO");
                Get<TextBlock>("StateDescription").Text = Copy("Checking and updating your installed copy before launch. Your saves and settings are preserved.", "Comprobando y actualizando tu copia instalada antes de iniciar. Se conservan tus partidas y ajustes.");
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
            bool failed = false, releasePrepared = false;
            var previousInstallation = action == "--download-update" ? new Dictionary<string, object> {
                { "installed", installed }, { "ready", ready }, { "update_available", updateAvailable },
                { "hd_textures_installed", hdTexturesInstalled }, { "spanish_installed", spanishInstalled },
                { "spanish_audio_installed", spanishAudioInstalled }, { "language", language }, { "install_dir", gameDirectory }, { "source_mode", sourceMode }
            } : null;
            Get<TextBlock>("StatusText").Foreground = new SolidColorBrush(Color.FromRgb(184, 183, 181));
            Get<TextBlock>("StatusText").Text = action == "--play" ? Copy("Verifying your copy before launch…", "Verificando tu copia antes de iniciar…")
                : action == "--import-iso" || action == "--use-iso" ? Copy("Checking your disc image…", "Comprobando la imagen del disco…")
                : action == "--update" ? Copy("Updating your installed game…", "Actualizando tu juego instalado…")
                : action == "--download-update" ? Copy("Downloading and preparing the update…", "Descargando y preparando la actualización…")
                : action == "--use-installation" ? Copy("Checking the selected installation…", "Comprobando la instalación seleccionada…")
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
                            object kind;
                            if (action == "--download-update" && item.TryGetValue("event", out kind) && Object.Equals(kind, "release_ready")) releasePrepared = true;
                            window.Dispatcher.Invoke(new Action(() => ApplyState(item)));
                        }
                        process.WaitForExit(); errorText = errors.Result;
                        return process.ExitCode;
                    }
                });
                failed = code != 0 || (action == "--download-update" && !releasePrepared);
                if (failed) {
                    if (!String.IsNullOrWhiteSpace(errorText)) Error(errorText.Length > 500 ? errorText.Substring(0, 500) : errorText);
                    else if (code == 0 && action == "--download-update") Error(Copy("The update was not prepared. Your installed game has not been changed.", "La actualización no se preparó. No se modificó tu juego instalado."));
                    else Error(Get<TextBlock>("StatusText").Text);
                }
            } catch (Exception ex) { failed = true; Error(ex.Message); }
            finally {
                try { if (cancelFile != null && File.Exists(cancelFile)) File.Delete(cancelFile); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
                cancelFile = null; busy = false; cancelRequested = false;
                if (failed && action == "--status") freshStatus = false;
                Get<ProgressBar>("Progress").IsIndeterminate = false;
                if (failed && previousInstallation != null) ApplyState(previousInstallation);
                if (!failed && (action == "--use-iso" || action == "--import-iso" || action == "--use-installation")) { sourceOpen = false; manageOpen = false; }
                SetButtons();
                if (closing) window.Close();
            }
            if (!failed && releasePrepared) window.Close();
            if (!failed && action == "--play") window.WindowState = WindowState.Minimized;
        }

#if LAUNCHER_TESTING
        public void RenderPreview(string path, string state)
        {
            if (state == "source" || state == "spanish-source") {
                sourceOpen = true;
                language = state == "spanish-source" ? "es" : "en";
                state = "fresh";
            }
            manageOpen = state == "manage" || state == "spanish-manage" || state == "fresh-manage";
            if (state == "manage") state = "hd-installed";
            if (state == "spanish-manage") state = "spanish-ready";
            if (state == "shaders" || state == "spanish-shaders") { busy = true; cancelFile = "preview"; }
            if (state == "new-release" || state == "spanish-offline") {
                language = state == "spanish-offline" ? "es" : "en";
                releaseStatus = state == "spanish-offline" ? "unavailable" : "available";
                latestRelease = "0.7";
                releaseUrl = "https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7";
                state = state == "spanish-offline" ? "spanish-ready" : "ready";
            }
            if (state == "spanish-ready") ApplyState(new Dictionary<string, object> { { "installed", true }, { "ready", true }, { "hd_textures_installed", true }, { "spanish_installed", true }, { "language", "es" }, { "message", "Instalación verificada. Todo listo para jugar." }, { "percent", 100 } });
            else if (state == "update" || state == "spanish-update") ApplyState(new Dictionary<string, object> { { "installed", true }, { "ready", false }, { "update_available", true }, { "language", state == "spanish-update" ? "es" : "en" }, { "message", "Update available. Choose Update Game; your installed data, saves and add-ons will be reused without the ISO." } });
            else if (state == "spanish-shaders") ApplyState(new Dictionary<string, object> { { "event", "shader_prepare" }, { "language", "es" }, { "message", "Preparando shaders — 2.220 de 4.440" }, { "percent", 50 } });
            else if (state == "ready" || state == "hd-installed") ApplyState(new Dictionary<string, object> { { "installed", true }, { "ready", true }, { "hd_textures_installed", state == "hd-installed" }, { "message", "Installation verified. Ready to play." }, { "percent", 100 } });
            else if (state == "shaders") ApplyState(new Dictionary<string, object> { { "event", "shader_prepare" }, { "message", "Preparing shaders — 2,220 of 4,440" }, { "percent", 50 } });
            else if (state == "importing") {
                busy = true; cancelFile = "preview";
                ApplyState(new Dictionary<string, object> { { "message", "Preparing HD menus and HUD…" }, { "percent", 78 } });
            } else ApplyState(new Dictionary<string, object> { { "message", "Select Game to use your Xbox ISO directly, import it once, or reuse an existing installation." } });
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
                if (SetupProcess.TryRecover(AppDomain.CurrentDomain.BaseDirectory)) return 0;
                var app = new Application();
                var launcher = new Launcher();
                launcher.completeUpdate = Array.IndexOf(args, "--complete-update") >= 0;
                return app.Run(launcher.Window);
            } catch (Exception ex) {
                MessageBox.Show(ex.Message, "Darkwatch: Darker Edition", MessageBoxButton.OK, MessageBoxImage.Error); return 1;
            }
        }
#endif
    }
}
