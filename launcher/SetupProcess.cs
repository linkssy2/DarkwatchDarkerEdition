using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;

namespace DarkwatchDarkerEdition
{
    public static class SetupProcess
    {
        public static string InstallRoot(string package) { return Path.Combine(package, "GameData"); }

        static bool RealPath(string path, bool directory, bool optional = false)
        {
            FileAttributes attributes;
            try { attributes = File.GetAttributes(path); }
            catch (FileNotFoundException) { if (optional) return false; throw; }
            catch (DirectoryNotFoundException) { if (optional) return false; throw; }
            if ((attributes & FileAttributes.ReparsePoint) != 0 || ((attributes & FileAttributes.Directory) != 0) != directory)
                throw new IOException("The update recovery files must be regular files and folders without links.");
            return true;
        }

        static bool PendingUpdate(string package)
        {
            RealPath(package, true);
            string stage = Path.Combine(package, ".launcher-update");
            if (!RealPath(stage, true, true)) return false;
            string journal = Path.Combine(stage, "transaction.json");
            if (!RealPath(journal, false, true)) return false;
            const int maximum = 8 * 1024 * 1024;
            try {
                using (var input = new FileStream(journal, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete)) {
                    if (input.Length > maximum) throw new IOException("The update recovery record is too large.");
                    using (var reader = new StreamReader(input, new UTF8Encoding(false, true), true)) {
                        var json = new JavaScriptSerializer { MaxJsonLength = maximum, RecursionLimit = 64 };
                        var value = json.DeserializeObject(reader.ReadToEnd()) as Dictionary<string, object>;
                        object phase;
                        if (value == null || !value.TryGetValue("phase", out phase)) throw new ArgumentException();
                        if (Object.Equals(phase, "prepared") || Object.Equals(phase, "applying")) return true;
                        if (Object.Equals(phase, "committed") || Object.Equals(phase, "rolled_back")) return false;
                        throw new ArgumentException();
                    }
                }
            } catch (ArgumentException error) {
                throw new IOException("The update recovery record is invalid. Keep this folder intact and restore the complete launcher package.", error);
            } catch (InvalidOperationException error) {
                throw new IOException("The update recovery record is invalid. Keep this folder intact and restore the complete launcher package.", error);
            }
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct StartupInfo {
            public uint cb;
            public string reserved, desktop, title;
            public uint x, y, width, height, xChars, yChars, fill, flags;
            public ushort show, reservedBytes;
            public IntPtr reservedData, input, output, error;
        }
        [StructLayout(LayoutKind.Sequential)]
        struct ProcessInfo { public IntPtr process, thread; public uint pid, tid; }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        static extern bool CreateProcessW(string application, StringBuilder command, IntPtr processAttributes,
            IntPtr threadAttributes, bool inheritHandles, uint flags, IntPtr environment, string directory,
            ref StartupInfo startup, out ProcessInfo process);
        [DllImport("kernel32.dll")]
        static extern bool CloseHandle(IntPtr handle);

        public static bool TryRecover(string package)
        {
            package = Path.GetFullPath(package);
            if (!PendingUpdate(package)) return false;
            string runner = Path.Combine(package, ".launcher-update", "runner");
            RealPath(runner, true);
            string python = Path.Combine(runner, "python.exe");
            string script = Path.Combine(runner, "release_update.py");
            RealPath(python, false); RealPath(script, false);
            var folders = new Stack<string>(); folders.Push(runner);
            while (folders.Count != 0) {
                foreach (string entry in Directory.EnumerateFileSystemEntries(folders.Pop())) {
                    bool directory = (File.GetAttributes(entry) & FileAttributes.Directory) != 0;
                    RealPath(entry, directory);
                    if (directory) folders.Push(entry);
                }
            }
            string arguments = Quote(python) + " -B " + Quote(script) + " --recover " + Quote(package)
                + " --wait-pid " + Process.GetCurrentProcess().Id + " --restart";
            var startup = new StartupInfo { cb = (uint)Marshal.SizeOf(typeof(StartupInfo)) };
            ProcessInfo process;
            // No inherited pipes: recovery must outlive the launcher and its backend readers.
            if (!CreateProcessW(python, new StringBuilder(arguments), IntPtr.Zero, IntPtr.Zero, false,
                    0x08000000, IntPtr.Zero, runner, ref startup, out process))
                throw new IOException("Could not start update recovery. Keep this folder intact and try again.",
                    new Win32Exception(Marshal.GetLastWin32Error()));
            CloseHandle(process.thread); CloseHandle(process.process);
            return true;
        }

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
            if (PendingUpdate(Path.GetFullPath(package)))
                throw new IOException("A launcher update is in progress. Close and reopen the launcher to finish recovery before playing or installing.");
            string python = Path.Combine(package, "payload", "python", "python.exe");
            string backend = Path.Combine(package, "payload", "setup_backend.py");
            if (!File.Exists(python) || !File.Exists(backend))
                throw new IOException("Launcher files are missing. Extract the complete Darker Edition package and try again.");
            string args = "-B " + Quote(backend) + " --package " + Quote(package) + " --install-root " + Quote(installRoot) + " " + action;
            if (argument != null) args += " " + Quote(argument);
            if (cancelFile != null) args += " --cancel-file " + Quote(cancelFile);
            if (action == "--download-update") args += " --launcher-pid " + Process.GetCurrentProcess().Id;
            var info = new ProcessStartInfo(python, args) {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                WorkingDirectory = package, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            };
            info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            return info;
        }
    }
}
