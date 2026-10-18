using System;
using System.Diagnostics;
using System.IO;
using System.Text;

namespace DarkwatchDarkerEdition
{
    public static class SetupProcess
    {
        public static string InstallRoot(string package) { return Path.Combine(package, "GameData"); }

        public static string Quote(string value)
        {
            var result = new StringBuilder("\""); int slashes = 0;
            foreach (char c in value) {
                if (c == '\\') { ++slashes; continue; }
                result.Append('\\', c == '"' ? slashes * 2 + 1 : slashes); result.Append(c); slashes = 0;
            }
            result.Append('\\', slashes * 2); return result.Append('"').ToString();
        }

        public static ProcessStartInfo Create(string package, string installRoot, string action,
                                              string argument = null, string cancelFile = null)
        {
            string python = Path.Combine(package, "payload", "python", "python.exe");
            string backend = Path.Combine(package, "payload", "setup_backend.py");
            if (!File.Exists(python) || !File.Exists(backend))
                throw new IOException("Launcher files are missing. Extract the complete Darker Edition package and try again.");
            string args = "-B " + Quote(backend) + " --package " + Quote(package) + " --install-root " + Quote(installRoot) + " " + action;
            if (argument != null) args += " " + Quote(argument);
            if (cancelFile != null) args += " --cancel-file " + Quote(cancelFile);
            var info = new ProcessStartInfo(python, args) {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                WorkingDirectory = package, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            };
            info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            return info;
        }
    }
}
