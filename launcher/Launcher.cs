using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
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
[assembly: AssemblyVersion("0.3.0.0")]
[assembly: AssemblyFileVersion("0.3.0.0")]
[assembly: AssemblyInformationalVersion("0.3")]
#endif

namespace DarkwatchDarkerEdition
{
    public sealed class Launcher
    {
        public const string DiscImageFilter = "Xbox disc images (*.iso;*.xiso)|*.iso;*.xiso";
        readonly Window window;
        readonly string package = AppDomain.CurrentDomain.BaseDirectory;
        readonly string installRoot = SetupProcess.InstallRoot(AppDomain.CurrentDomain.BaseDirectory);
        readonly JavaScriptSerializer json = new JavaScriptSerializer();
        bool busy, installed, ready, closing, cancelRequested;
        string cancelFile, gameDirectory;
        readonly Action cancelPreparation;

        T Get<T>(string name) where T : FrameworkElement { return (T)window.FindName(name); }
        public Window Window { get { return window; } }

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
                var dialog = new OpenFileDialog { Title = "Select your original Xbox Darkwatch disc image", Filter = DiscImageFilter, CheckFileExists = true, Multiselect = false };
                if (dialog.ShowDialog(window) == true) await Run("--import-iso", dialog.FileName);
            };
            Get<Button>("VerifyButton").Click += async delegate { await Run("--verify", null); };
            Get<Button>("PlayButton").Click += async delegate { await Run("--play", null); };
            Get<Button>("CancelButton").Click += delegate { Cancel(); };
            Get<Button>("FolderButton").Click += delegate {
                try { Process.Start(new ProcessStartInfo { FileName = Directory.Exists(gameDirectory) ? gameDirectory : installRoot, UseShellExecute = true }); }
                catch (Exception ex) { Error(ex.Message); }
            };
            Get<Button>("CoopButton").Click += delegate { ShowCoop(Get<Border>("CoopPanel").Visibility != Visibility.Visible); };
            Get<Button>("CoopSaveButton").Click += async delegate { await SaveCoop(); };
            Get<Button>("CoopJoinButton").Click += delegate { JoinCoop(); };
            window.Closing += delegate(object sender, System.ComponentModel.CancelEventArgs e) {
                if (!busy) return;
                e.Cancel = true;
                if (cancelPreparation != null) { Cancel(); return; }
                if (MessageBox.Show(window, "Cancel the current operation and close the launcher? Your existing installation will be kept.", "Darkwatch: Darker Edition", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) == MessageBoxResult.Yes) {
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
            Get<Button>("CancelButton").Visibility = busy && (cancelFile != null || cancelPreparation != null) ? Visibility.Visible : Visibility.Collapsed;
            Get<Button>("CancelButton").IsEnabled = busy && !cancelRequested;
            Get<Button>("ImportButton").Content = installed ? "IMPORT / REPAIR" : "IMPORT ISO";
            Get<Button>("ImportButton").Background = (Brush)new BrushConverter().ConvertFromString(ready ? "#20232A" : "#701C25");
            Get<Button>("PlayButton").Background = (Brush)new BrushConverter().ConvertFromString(ready ? "#701C25" : "#20232A");
            // Only the host needs an installed game; player 2 joins from the package alone.
            Get<Button>("CoopSaveButton").IsEnabled = !busy && installed;
            Get<Button>("CoopJoinButton").IsEnabled = !busy;
        }

        void ShowCoop(bool show)
        {
            Get<Border>("CoopPanel").Visibility = show ? Visibility.Visible : Visibility.Collapsed;
            Get<StackPanel>("Overview").Visibility = show ? Visibility.Collapsed : Visibility.Visible;
            Get<Button>("CoopButton").Content = show ? "BACK" : "CO-OP";
        }

        // Matches the game's coop_code: letters, digits, - and _, 1 to 32 of them.
        static bool ValidCoopCode(string code)
        {
            if (code.Length < 1 || code.Length > 32) return false;
            foreach (char c in code)
                if (!(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '-' || c == '_')) return false;
            return true;
        }

        bool CoopPort(out int port)
        {
            return int.TryParse(Get<TextBox>("CoopPort").Text.Trim(), out port) && port >= 1024 && port <= 65535;
        }

        void ApplyCoop(Dictionary<string, object> coop)
        {
            object value;
            if (coop.TryGetValue("host", out value)) Get<CheckBox>("CoopHost").IsChecked = Convert.ToBoolean(value);
            if (coop.TryGetValue("campaign", out value)) Get<CheckBox>("CoopCampaign").IsChecked = Convert.ToBoolean(value);
            if (coop.TryGetValue("port", out value)) Get<TextBox>("CoopPort").Text = Convert.ToString(value);
            if (coop.TryGetValue("code", out value) && !String.IsNullOrEmpty(Convert.ToString(value)))
                Get<TextBox>("CoopCode").Text = Convert.ToString(value);
        }

        async Task SaveCoop()
        {
            bool host = Get<CheckBox>("CoopHost").IsChecked == true, campaign = Get<CheckBox>("CoopCampaign").IsChecked == true;
            string code = Get<TextBox>("CoopCode").Text.Trim();
            int port;
            if (!CoopPort(out port)) { Error("The co-op port must be a number from 1024 to 65535."); return; }
            if ((host || code.Length > 0) && !ValidCoopCode(code)) { Error("The co-op code must be 1 to 32 letters, digits, - or _."); return; }
            // The code's characters need no JSON escaping.
            string settings = "{\"host\":" + (host ? "true" : "false") + ",\"code\":\"" + code + "\",\"port\":" + port +
                              ",\"campaign\":" + (campaign ? "true" : "false") + "}";
            await Run("--coop", settings);
        }

        void JoinCoop()
        {
            string address = Get<TextBox>("CoopAddress").Text.Trim(), code = Get<TextBox>("CoopCode").Text.Trim();
            if (address.Length == 0) { Error("Enter the host's address, such as 192.168.1.24."); return; }
            if (!ValidCoopCode(code)) { Error("The co-op code must be 1 to 32 letters, digits, - or _."); return; }
            int port;
            // A port typed with the address wins; otherwise a non-default port field applies.
            if (address.IndexOf(':') < 0 && CoopPort(out port) && port != 41330) address += ":" + port;
            string client = Path.Combine(package, "payload", "runtime", "darkwatch_coop_client.exe");
            if (!File.Exists(client)) { Error("The co-op client is missing. Extract the complete Darker Edition package."); return; }
            try {
                Process.Start(new ProcessStartInfo(client, SetupProcess.Quote(address) + " " + SetupProcess.Quote(code)) {
                    UseShellExecute = false, WorkingDirectory = Path.GetDirectoryName(client)
                });
                Get<TextBlock>("StatusText").Foreground = new SolidColorBrush(Color.FromRgb(184, 183, 181));
                Get<TextBlock>("StatusText").Text = "Player 2 started. Click its window to play with keyboard and mouse; F8 releases the mouse.";
            } catch (Exception ex) { Error("The co-op client could not start: " + ex.Message); }
        }

        void ApplyState(Dictionary<string, object> item)
        {
            object value;
            if (item.TryGetValue("installed", out value)) installed = Convert.ToBoolean(value);
            if (item.TryGetValue("ready", out value)) ready = Convert.ToBoolean(value);
            if (item.TryGetValue("install_dir", out value)) gameDirectory = Convert.ToString(value);
            if (item.TryGetValue("message", out value)) Get<TextBlock>("StatusText").Text = Convert.ToString(value);
            if (item.TryGetValue("coop", out value) && value is Dictionary<string, object>) ApplyCoop((Dictionary<string, object>)value);
            if (item.TryGetValue("percent", out value) && value != null) {
                Get<ProgressBar>("Progress").IsIndeterminate = false;
                Get<ProgressBar>("Progress").Value = Math.Max(0, Math.Min(100, Convert.ToDouble(value)));
            }
            Get<TextBlock>("StateTitle").Text = ready ? "THE NIGHT AWAITS" : "PREPARE YOUR HUNT";
            Get<TextBlock>("StateDescription").Text = ready
                ? "Your copy is ready. Enter the hunt, or adjust your graphics and controls from the game’s Options menu."
                : "Bring your own original Xbox Darkwatch ISO. Import it once to prepare Darker Edition on this PC.";
            object kind;
            if (cancelPreparation != null || (item.TryGetValue("event", out kind) && Object.Equals(kind, "shader_prepare"))) {
                Get<TextBlock>("StateTitle").Text = "PREPARING SHADERS";
                Get<TextBlock>("StateDescription").Text = "Preparing Darkwatch’s graphics before the hunt. This only runs when shaders need preparation. Prepared shaders are reused on later launches.";
            }
            if (cancelRequested && item.TryGetValue("event", out kind) &&
                (Object.Equals(kind, "progress") || Object.Equals(kind, "shader_prepare")))
                Get<TextBlock>("StatusText").Text = "Canceling safely…";
            SetButtons();
        }

        void Error(string message)
        {
            Get<TextBlock>("StatusText").Text = message;
            Get<TextBlock>("StatusText").Foreground = new SolidColorBrush(Color.FromRgb(229, 153, 139));
        }

        void Cancel()
        {
            if (cancelPreparation != null) {
                try {
                    cancelPreparation();
                    cancelRequested = true;
                    Get<TextBlock>("StatusText").Text = "Canceling safely…";
                    Get<Button>("CancelButton").IsEnabled = false;
                } catch (Exception ex) { Error("Could not request cancellation: " + ex.Message); }
                return;
            }
            if (cancelFile == null) return;
            try {
                File.WriteAllText(cancelFile, "cancel");
                cancelRequested = true;
                Get<TextBlock>("StatusText").Text = "Canceling safely…";
                Get<Button>("CancelButton").IsEnabled = false;
            } catch (Exception ex) { Error("Could not request cancellation: " + ex.Message); closing = false; }
        }

        async Task Run(string action, string argument)
        {
            if (busy) return;
            busy = true; cancelRequested = false;
            bool failed = false;
            Get<TextBlock>("StatusText").Foreground = new SolidColorBrush(Color.FromRgb(184, 183, 181));
            Get<TextBlock>("StatusText").Text = action == "--play" ? "Verifying your copy before launch…" : action == "--import-iso" ? "Checking your disc image…" :
                action == "--coop" ? "Saving co-op settings…" : "Checking installation…";
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
                        if (!process.Start()) throw new IOException("The setup helper could not start.");
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
            if (state == "ready") ApplyState(new Dictionary<string, object> { { "installed", true }, { "ready", true }, { "message", "Installation verified. Ready to play." }, { "percent", 100 } });
            else if (state == "shaders") ApplyState(new Dictionary<string, object> { { "event", "shader_prepare" }, { "message", "Preparing shaders — 2,220 of 4,440" }, { "percent", 50 } });
            else if (state == "coop") {
                ApplyState(new Dictionary<string, object> { { "installed", true }, { "ready", true }, { "message", "Hosting network co-op on UDP 41330 from the next launch. Allow it in Windows Firewall." },
                    { "percent", 100 }, { "coop", new Dictionary<string, object> { { "host", true }, { "code", "night-hunt" }, { "port", 41330 }, { "campaign", true } } } });
                Get<TextBox>("CoopAddress").Text = "192.168.1.24";
                ShowCoop(true);
            }
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
