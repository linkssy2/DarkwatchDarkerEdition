using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows;

[assembly: AssemblyTitle("Play Darkwatch: Darker Edition")]
[assembly: AssemblyProduct("Darkwatch: Darker Edition")]
[assembly: AssemblyVersion("0.6.1.0")]
[assembly: AssemblyFileVersion("0.6.1.0")]
[assembly: AssemblyInformationalVersion("0.6.1")]

namespace DarkwatchDarkerEdition
{
    public static class DirectPlay
    {
        public static void Run(string package, string installRoot, Action<Dictionary<string, object>> progress = null, string cancelFile = null)
        {
            var json = new JavaScriptSerializer();
            string failure = null;
            string language = "en";
            bool started = false, cancelled = false;
            // Use the same verified installation and launch lock as the full launcher.
            using (var process = new Process { StartInfo = SetupProcess.Create(package, installRoot, "--play", cancelFile: cancelFile) }) {
                if (!process.Start()) throw new IOException("The game setup helper could not start.");
                var errors = process.StandardError.ReadToEndAsync();
                string line;
                while ((line = process.StandardOutput.ReadLine()) != null) {
                    Dictionary<string, object> item;
                    try { item = json.Deserialize<Dictionary<string, object>>(line); }
                    catch (ArgumentException) { continue; }
                    object kind, message, ready, pid, wasCancelled, selectedLanguage;
                    if (item == null || !item.TryGetValue("event", out kind)) continue;
                    if (item.TryGetValue("language", out selectedLanguage)) language = Object.Equals(selectedLanguage, "es") ? "es" : "en";
                    if (Object.Equals(kind, "error") && item.TryGetValue("message", out message))
                        failure = Convert.ToString(message);
                    if (Object.Equals(kind, "error") && item.TryGetValue("cancelled", out wasCancelled) && Object.Equals(wasCancelled, true)) cancelled = true;
                    if (Object.Equals(kind, "shader_prepare") && progress != null) {
                        item["language"] = language;
                        progress(item);
                    }
                    if (Object.Equals(kind, "result") && item.TryGetValue("ready", out ready) && Object.Equals(ready, true)
                        && item.TryGetValue("pid", out pid) && pid is int && (int)pid > 0)
                        started = true;
                }
                process.WaitForExit();
                string stderr = errors.Result;
                if (cancelled) throw new OperationCanceledException(language == "es" ? "Se canceló la preparación de shaders. Se conservan los shaders completados." : "Shader preparation was canceled. Completed shaders are kept.");
                if (process.ExitCode != 0 || !started || failure != null) {
                    if (String.IsNullOrWhiteSpace(failure)) failure = String.IsNullOrWhiteSpace(stderr) ? (language == "es" ? "No se pudo iniciar Darkwatch." : "Darkwatch could not start.") : stderr;
                    failure = Launcher.Localize(failure, language);
                    throw new IOException((failure.Length > 500 ? failure.Substring(0, 500) : failure)
                        + (language == "es" ? "\n\nAbre Darkwatch Darker Edition.exe para importar o reparar el juego." : "\n\nOpen Darkwatch Darker Edition.exe to import or repair your game."));
                }
            }
        }

        [STAThread]
        public static int Main()
        {
            try {
                string package = AppDomain.CurrentDomain.BaseDirectory;
                string installRoot = SetupProcess.InstallRoot(package);
                Directory.CreateDirectory(installRoot);
                string cancelFile = Path.Combine(installRoot, ".cancel-" + Guid.NewGuid().ToString("N"));
                var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
                Launcher preparation = null;
                app.Startup += async delegate {
                    int result = 0;
                    try {
                        await Task.Run(() => Run(package, installRoot, item => app.Dispatcher.Invoke(new Action(() => {
                            if (preparation == null) {
                                preparation = Launcher.Preparing(() => File.WriteAllText(cancelFile, "cancel"));
                                preparation.Window.Show();
                            }
                            preparation.UpdatePreparation(item);
                        })), cancelFile));
                    } catch (OperationCanceledException) { result = 1; }
                    catch (Exception ex) {
                        result = 1;
                        MessageBox.Show(ex.Message, "Darkwatch: Darker Edition", MessageBoxButton.OK, MessageBoxImage.Error);
                    } finally {
                        if (preparation != null) preparation.FinishPreparation();
                        try { if (File.Exists(cancelFile)) File.Delete(cancelFile); }
                        catch (IOException) { }
                        catch (UnauthorizedAccessException) { }
                        app.Shutdown(result);
                    }
                };
                return app.Run();
            } catch (Exception ex) {
                MessageBox.Show(ex.Message, "Darkwatch: Darker Edition", MessageBoxButton.OK, MessageBoxImage.Error);
                return 1;
            }
        }
    }
}
