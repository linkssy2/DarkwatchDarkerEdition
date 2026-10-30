"""Exercise the real direct-start executable with a harmless protocol fixture.

No game, production installation backend, or visible launcher is started.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319"
REFERENCES = ["System.dll", "System.Core.dll", "System.Web.Extensions.dll", "System.Xaml.dll", "System.Windows.Forms.dll",
              "WPF/PresentationFramework.dll", "WPF/PresentationCore.dll", "WPF/WindowsBase.dll"]

HELPER = r'''
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
class DirectPlayFixture {
    [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int kind);
    [DllImport("kernel32.dll")] static extern uint GetFileType(IntPtr handle);
    static int Main(string[] args) {
        if(Environment.GetEnvironmentVariable("DARKWATCH_DIRECT_FIXTURE_MODE")=="recover") {
            int parent=0;
            for(int i=0;i<args.Length-1;++i)if(args[i]=="--wait-pid")parent=Int32.Parse(args[i+1]);
            bool exited=false;
            try {using(var process=Process.GetProcessById(parent))exited=process.WaitForExit(5000);}
            catch(ArgumentException) {exited=true;}
            File.WriteAllText(Environment.GetEnvironmentVariable("DARKWATCH_DIRECT_FIXTURE_REPORT"),
                new JavaScriptSerializer().Serialize(new {args=args,cwd=Environment.CurrentDirectory,parentExited=exited,
                    input=GetFileType(GetStdHandle(-10)),output=GetFileType(GetStdHandle(-11)),error=GetFileType(GetStdHandle(-12))}),Encoding.UTF8);
            return 0;
        }
        Console.OutputEncoding=new UTF8Encoding(false);
        string mode=Environment.GetEnvironmentVariable("DARKWATCH_DIRECT_FIXTURE_MODE");
        var json=new JavaScriptSerializer();
        File.WriteAllText(Environment.GetEnvironmentVariable("DARKWATCH_DIRECT_FIXTURE_REPORT"),
            json.Serialize(new {args=args,cwd=Environment.CurrentDirectory,
                encoding=Environment.GetEnvironmentVariable("PYTHONIOENCODING")}),Encoding.UTF8);
        Console.WriteLine("not JSON"); Console.WriteLine("null");
        if(mode=="cold-es"||mode=="update-es"||mode=="error-es") Console.WriteLine("{\"event\":\"status\",\"language\":\"es\"}");
        Console.WriteLine("{\"event\":\"progress\",\"percent\":100}");
        if(mode=="update"||mode=="update-es") {
            Console.WriteLine("{\"event\":\"progress\",\"message\":\"Preparing selectable characters...\",\"percent\":80}");
            Console.WriteLine("{\"event\":\"progress\",\"message\":\"Preserving saves, controls, and shader cache\",\"percent\":95}");
        }
        if(mode=="cold"||mode=="cold-es"||mode=="cancel") {
            Console.WriteLine("{\"event\":\"shader_prepare\",\"message\":\"Preparing shaders — 1 of 2\",\"percent\":50,\"completed\":1,\"total\":2}");
            if(mode=="cancel") {
                string token=null;
                for(int i=0;i<args.Length-1;++i)if(args[i]=="--cancel-file")token=args[i+1];
                for(int i=0;i<300&&!File.Exists(token);++i)Thread.Sleep(10);
                if(!File.Exists(token))return 9;
                Console.WriteLine("{\"event\":\"error\",\"message\":\"Canceled safely\",\"cancelled\":true}");
                return 1;
            }
            Console.WriteLine("{\"event\":\"shader_prepare\",\"message\":\"Preparing shaders — 2 of 2\",\"percent\":100,\"completed\":2,\"total\":2}");
        }
        if(mode=="stderr") {Console.Error.Write(new string('É',700));return 2;}
        if(mode=="error-es") { Console.WriteLine("{\"event\":\"error\",\"message\":\"Close Darkwatch before installing, repairing, or starting another copy.\"}"); return 1; }
        if(mode=="large-stderr") Console.Error.Write(new string('E',262144));
        if(mode=="error"||mode=="error-then-success") {
            Console.WriteLine(json.Serialize(new { @event="error",message=new string('誤',700)}));
            if(mode=="error") return 1;
        }
        if(mode=="missing-result") return 0;
        if(mode=="not-ready") {Console.WriteLine("{\"event\":\"result\",\"ready\":false,\"pid\":123}");return 0;}
        if(mode=="missing-pid") {Console.WriteLine("{\"event\":\"result\",\"ready\":true}");return 0;}
        if(mode=="bad-pid") {Console.WriteLine("{\"event\":\"result\",\"ready\":true,\"pid\":\"123\"}");return 0;}
        if(mode=="zero-pid") {Console.WriteLine("{\"event\":\"result\",\"ready\":true,\"pid\":0}");return 0;}
        Console.WriteLine("{\"event\":\"result\",\"ready\":true,\"pid\":123}");
        return mode=="nonzero"?3:0;
    }
}
'''

HARNESS = r'''
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using DarkwatchDarkerEdition;
class DirectPlayHarness {
    [STAThread] static int Main(string[] args) {
        Console.OutputEncoding=new UTF8Encoding(false);
        var json=new JavaScriptSerializer();
        try {
            if(args[0]=="recover") {
                bool started=SetupProcess.TryRecover(args[1]);
                Console.Write(json.Serialize(new {ok=true,started=started,pid=Process.GetCurrentProcess().Id}));
            } else if(args[0]=="info"||args[0]=="download-info"||args[0]=="status-info") {
                var info=SetupProcess.Create(args[1],args[2],args[0]=="download-info"?"--download-update":args[0]=="status-info"?"--status":"--play");
                Console.Write(json.Serialize(new {file=info.FileName,arguments=info.Arguments,
                    pid=Process.GetCurrentProcess().Id,
                    cwd=info.WorkingDirectory,shell=info.UseShellExecute,hidden=info.CreateNoWindow,
                    stdout=info.RedirectStandardOutput,stderr=info.RedirectStandardError,
                    outcode=info.StandardOutputEncoding.CodePage,errcode=info.StandardErrorEncoding.CodePage,
                    encoding=info.EnvironmentVariables["PYTHONIOENCODING"]}));
            } else if(args[0]=="prepare"||args[0]=="prepare-es"||args[0]=="update"||args[0]=="update-es"||args[0]=="cancel"||args[0]=="close") {
                int updates=0,cancels=0;Launcher view=null;
                string token=Path.Combine(args[2],".cancel-fixture");Directory.CreateDirectory(args[2]);
                try {
                    DirectPlay.Run(args[1],args[2],item=>{
                        ++updates;
                        if(view==null)view=Launcher.Preparing(()=>{++cancels;File.WriteAllText(token,"cancel");});
                        view.UpdatePreparation(item);
                        if(view.Window.IsVisible)throw new Exception("Preparation fixture showed a window");
                        string title=args[0]=="update"?"PREPARING YOUR GAME":args[0]=="update-es"?"PREPARANDO EL JUEGO":args[0]=="prepare-es"?"PREPARANDO SHADERS":"PREPARING SHADERS";
                        if(((TextBlock)view.Window.FindName("StateTitle")).Text!=title)throw new Exception("Missing preparation title");
                        if(args[0]=="prepare-es"&&!((TextBlock)view.Window.FindName("StatusText")).Text.StartsWith("Preparando shaders — "))throw new Exception("Shader progress stayed English");
                        if(((Grid)view.Window.FindName("LaunchActions")).Visibility!=Visibility.Collapsed)throw new Exception("Preparation exposes launch actions");
                        if(((StackPanel)view.Window.FindName("ManagePanel")).Visibility!=Visibility.Collapsed || ((ComboBox)view.Window.FindName("LanguageChoice")).IsEnabled)throw new Exception("Preparation exposes language mutation");
                        if(((ProgressBar)view.Window.FindName("Progress")).Value!=Convert.ToDouble(item["percent"]))throw new Exception("Wrong shader progress");
                        if(((Image)view.Window.FindName("Cover")).Source==null)throw new Exception("Preparation lost artwork");
                        if(args[0]=="cancel")((Button)view.Window.FindName("CancelButton")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                        if(args[0]=="close")view.Window.Close();
                    },token);
                    Console.Write(json.Serialize(new {ok=true,updates=updates,shown=false}));
                } catch(OperationCanceledException) {
                    Console.Write(json.Serialize(new {ok=false,cancelled=true,updates=updates,cancels=cancels,shown=false}));
                } finally {
                    if(view!=null)view.FinishPreparation();
                    if(File.Exists(token))File.Delete(token);
                }
            } else {
                DirectPlay.Run(args[1],args[2]);
                Console.Write("{\"ok\":true}");
            }
        } catch(Exception e) {
            Console.Write(json.Serialize(new {ok=false,type=e.GetType().FullName,message=e.Message}));
        }
        return 0;
    }
}
'''


@unittest.skipUnless(os.name == "nt" and (FRAMEWORK / "csc.exe").exists(), "Requires Windows .NET Framework")
class DirectPlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="darkwatch-direct-")
        cls.build = Path(cls.temp.name).resolve() / "package space 測試 é 🦇"
        cls.build.mkdir()
        cls.evidence = Path(os.environ.get("DARKWATCH_DIRECT_PLAY_EVIDENCE", cls.build / "evidence"))
        cls.evidence.mkdir(parents=True, exist_ok=True)
        cls.install = cls.build / "installed games 日本語"
        cls.helper = cls.build / "payload/python/python.exe"
        cls.helper.parent.mkdir(parents=True)
        cls.backend = cls.build / "payload/setup_backend.py"
        cls.backend.write_text("# Harmless protocol fixture; never interpreted.\n", encoding="utf-8")
        (cls.build / "Helper.cs").write_text(HELPER, encoding="utf-8")
        (cls.build / "Harness.cs").write_text(HARNESS, encoding="utf-8")
        references = [f"/reference:{FRAMEWORK / name}" for name in REFERENCES]
        sources = [str(ROOT / "launcher" / name) for name in ["SetupProcess.cs", "DirectPlay.cs", "Launcher.cs"]]
        resources = [f"/resource:{ROOT / 'launcher' / path},{name}" for path, name in [
            ("MainWindow.xaml", "Darkwatch.MainWindow.xaml"), ("assets/cover-darker-edition.png", "Darkwatch.Cover.png"),
            ("assets/insignia.png", "Darkwatch.Insignia.png")]]

        def compile_cs(arguments, target="exe"):
            result = subprocess.run([str(FRAMEWORK / "csc.exe"), "/nologo", f"/target:{target}",
                                     "/platform:x64", "/optimize+", *arguments],
                                    capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)

        compile_cs([f"/reference:{FRAMEWORK / 'System.Web.Extensions.dll'}",
                    f"/out:{cls.helper}", str(cls.build / "Helper.cs")])
        cls.harness = cls.build / "DirectPlayHarness.exe"
        compile_cs([*references, *resources, "/define:DIRECT_PLAY", "/main:DirectPlayHarness", f"/out:{cls.harness}",
                    *sources, str(cls.build / "Harness.cs")])
        cls.production = cls.build / "Play Darkwatch.exe"
        compile_cs([*references, *resources, "/define:DIRECT_PLAY", f"/out:{cls.production}",
                    f"/win32manifest:{ROOT / 'launcher/app.manifest'}",
                    f"/win32icon:{ROOT / 'launcher/assets/insignia.ico'}", *sources], "winexe")
        cls.launcher_production = cls.build / "Darkwatch Darker Edition.exe"
        compile_cs([*references, *resources, f"/out:{cls.launcher_production}",
                    f"/win32manifest:{ROOT / 'launcher/app.manifest'}", sources[0], sources[2]], "winexe")
        cls.results = {"real_backend_or_game_started": False, "fixture_results": {},
                       "source_sha256": {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources}}

    @classmethod
    def tearDownClass(cls):
        (cls.evidence / "report.json").write_text(json.dumps(cls.results, indent=2) + "\n", encoding="utf-8")
        cls.temp.cleanup()

    def run_fixture(self, mode="success", operation="run", package=None):
        record = self.evidence / f"{mode}-{operation}.json"
        record.unlink(missing_ok=True)
        environment = dict(os.environ, DARKWATCH_DIRECT_FIXTURE_MODE=mode,
                           DARKWATCH_DIRECT_FIXTURE_REPORT=str(record))
        result = subprocess.run([str(self.harness), operation, str(package or self.build), str(self.install)],
                                capture_output=True, encoding="utf-8-sig", env=environment, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(result.stderr, result.stderr)
        response = json.loads(result.stdout)
        self.results["fixture_results"][mode + "-" + operation] = response
        return response, record

    def recovery_package(self, name, phase="prepared"):
        package = self.build.parent / name
        runner = package / ".launcher-update/runner"
        runner.mkdir(parents=True)
        shutil.copyfile(self.helper, runner / "python.exe")
        (runner / "release_update.py").write_text("# Harmless recovery fixture; never interpreted.\n", encoding="utf-8")
        (runner.parent / "transaction.json").write_text(json.dumps({"phase": phase}), encoding="utf-8")
        return package

    def recovery_report(self, record):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                return json.loads(record.read_text(encoding="utf-8-sig"))
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.025)
        self.fail("Detached recovery fixture did not finish after its caller exited")

    def test_download_update_alone_passes_launcher_identity(self):
        for operation in ("info", "status-info", "download-info"):
            response, _ = self.run_fixture(operation=operation)
            if operation == "download-info":
                self.assertTrue(response["arguments"].endswith("--download-update --launcher-pid " + str(response["pid"])))
            else:
                self.assertNotIn("--launcher-pid", response["arguments"])

    def test_recovery_handoff_fixed_paths_detached_and_parent_exit(self):
        for phase in ("prepared", "applying"):
            with self.subTest(phase=phase):
                package = self.recovery_package("recovery " + phase + " 日本語 🦇", phase)
                journal = package / ".launcher-update/transaction.json"
                journal.write_text(json.dumps({"phase": phase, "runner": "C:/untrusted/evil.exe",
                                               "script": "../../evil.py", "restart": "cmd.exe"}), encoding="utf-8")
                started = time.monotonic()
                response, record = self.run_fixture("recover", "recover", package)
                self.assertTrue(response["ok"])
                self.assertTrue(response["started"])
                self.assertLess(time.monotonic() - started, 3, "Recovery must return rather than wait on its own caller")
                details = self.recovery_report(record)
                self.assertTrue(details["parentExited"], "The runner must outlive the bootstrap caller")
                self.assertEqual(details["args"], ["-B", str(package / ".launcher-update/runner/release_update.py"),
                                                 "--recover", str(package), "--wait-pid", str(response["pid"]), "--restart"])
                self.assertEqual(details["cwd"], str(package / ".launcher-update/runner"))
                for handle in ("input", "output", "error"):
                    self.assertNotEqual(details[handle], 3, "Recovery inherited a caller pipe: " + handle)

    def test_pending_recovery_blocks_backend_before_missing_payload(self):
        for phase in ("prepared", "applying"):
            package = self.recovery_package("block " + phase, phase)
            for operation in ("run", "status-info", "download-info"):
                response, record = self.run_fixture(operation=operation, package=package)
                self.assertFalse(response["ok"])
                self.assertEqual(response["type"], "System.IO.IOException")
                self.assertIn("update is in progress", response["message"])
                self.assertFalse(record.exists())

    def test_absent_or_terminal_transaction_does_not_launch_recovery(self):
        for package in (self.build, self.recovery_package("committed recovery", "committed"),
                        self.recovery_package("rolled back recovery", "rolled_back")):
            response, record = self.run_fixture("recover", "recover", package)
            self.assertTrue(response["ok"])
            self.assertFalse(response["started"])
            self.assertFalse(record.exists())
        for name in ("committed recovery", "rolled back recovery"):
            package = self.build.parent / name
            (package / "payload/python").mkdir(parents=True)
            shutil.copyfile(self.helper, package / "payload/python/python.exe")
            shutil.copyfile(self.backend, package / "payload/setup_backend.py")
            response, _ = self.run_fixture(package=package)
            self.assertTrue(response["ok"])

    def test_invalid_recovery_journal_and_missing_runner_fail_closed(self):
        values = ("{", "null", "[]", "{}", '{"phase":"unknown"}', '{"phase":false}', " " * (8 * 1024 * 1024 + 1))
        for number, content in enumerate(values):
            with self.subTest(number=number):
                package = self.recovery_package("invalid journal " + str(number))
                (package / ".launcher-update/transaction.json").write_text(content, encoding="utf-8")
                for operation in ("recover", "info"):
                    response, record = self.run_fixture("recover", operation, package)
                    self.assertFalse(response["ok"])
                    self.assertEqual(response["type"], "System.IO.IOException")
                    self.assertFalse(record.exists())
        for name in ("python.exe", "release_update.py"):
            package = self.recovery_package("missing runner " + name)
            (package / ".launcher-update/runner" / name).unlink()
            response, record = self.run_fixture("recover", "recover", package)
            self.assertFalse(response["ok"])
            self.assertFalse(record.exists())

    def test_recovery_rejects_linked_stage_journal_runner_and_dependencies(self):
        target = self.build.parent / "link target"
        target.mkdir()
        (target / "file").write_text("fixture", encoding="utf-8")
        for name in (".launcher-update", ".launcher-update/transaction.json", ".launcher-update/runner",
                     ".launcher-update/runner/python.exe", ".launcher-update/runner/release_update.py",
                     ".launcher-update/runner/python312.dll"):
            with self.subTest(name=name):
                package = self.recovery_package("linked " + name.replace("/", "-"))
                link = package / name
                directory = link.is_dir()
                if directory:
                    shutil.rmtree(link)
                else:
                    link.unlink(missing_ok=True)
                try:
                    link.symlink_to(target if directory else target / "file", target_is_directory=directory)
                except OSError as error:
                    if directory:
                        import _winapi
                        _winapi.CreateJunction(str(target), str(link))
                    else:
                        self.skipTest("Windows file symbolic links unavailable: " + str(error))
                response, record = self.run_fixture("recover", "recover", package)
                self.assertFalse(response["ok"])
                self.assertIn("without links", response["message"])
                self.assertFalse(record.exists())

    def test_production_entry_hands_off_recovery_before_loading_backend(self):
        for source in (self.production, self.launcher_production):
            with self.subTest(source=source.name):
                package = self.recovery_package("production recovery " + source.stem)
                executable = package / source.name
                shutil.copyfile(source, executable)
                record = self.evidence / ("production-recovery-" + source.stem + ".json")
                environment = dict(os.environ, DARKWATCH_DIRECT_FIXTURE_MODE="recover",
                                   DARKWATCH_DIRECT_FIXTURE_REPORT=str(record))
                result = subprocess.run([str(executable)], capture_output=True, env=environment, timeout=12)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout + result.stderr, b"")
                details = self.recovery_report(record)
                self.assertTrue(details["parentExited"])
                self.assertEqual(details["args"][2], "--recover")
                self.assertEqual(Path(details["args"][3]), package)
                self.assertFalse((package / "GameData").exists(), "Recovery must precede installation setup")

    def test_hidden_shared_helper_contract(self):
        response, _ = self.run_fixture(operation="info")
        self.assertEqual(response["file"], str(self.helper))
        self.assertEqual(response["cwd"], str(self.build))
        self.assertFalse(response["shell"])
        self.assertTrue(response["hidden"])
        self.assertTrue(response["stdout"])
        self.assertTrue(response["stderr"])
        self.assertEqual(response["outcode"], 65001)
        self.assertEqual(response["errcode"], 65001)
        self.assertEqual(response["encoding"], "utf-8")

    def test_success_exact_arguments_unicode_paths_and_working_directory(self):
        response, record = self.run_fixture()
        self.assertTrue(response["ok"])
        details = json.loads(record.read_text(encoding="utf-8-sig"))
        self.assertEqual(details["args"], ["-B", str(self.backend), "--package", str(self.build),
                                           "--install-root", str(self.install), "--play"])
        self.assertEqual(details["cwd"], str(self.build))
        self.assertEqual(details["encoding"], "utf-8")

    def test_json_and_stderr_errors_are_bounded_and_explain_repair(self):
        for mode, character in [("error", "誤"), ("stderr", "É")]:
            with self.subTest(mode=mode):
                response, _ = self.run_fixture(mode)
                self.assertFalse(response["ok"])
                self.assertEqual(response["type"], "System.IO.IOException")
                self.assertTrue(response["message"].startswith(character * 500 + "\n\n"))
                self.assertNotIn(character * 501, response["message"])
                self.assertIn("Darkwatch Darker Edition.exe", response["message"])
                self.assertIn("import or repair", response["message"])

    def test_invalid_success_claims_are_rejected(self):
        for mode in ["missing-result", "not-ready", "missing-pid", "bad-pid", "zero-pid", "nonzero", "error-then-success"]:
            with self.subTest(mode=mode):
                response, _ = self.run_fixture(mode)
                self.assertFalse(response["ok"], mode)
                self.assertEqual(response["type"], "System.IO.IOException")

    def test_stderr_is_drained_concurrently(self):
        response, _ = self.run_fixture("large-stderr")
        self.assertTrue(response["ok"])

    def test_cold_preparation_uses_themed_view_and_real_progress_without_showing_ui(self):
        response, _ = self.run_fixture("cold", operation="prepare")
        self.assertTrue(response["ok"])
        self.assertEqual(response["updates"], 2)
        self.assertFalse(response["shown"])

    def test_spanish_status_is_retained_for_direct_preparation_and_errors(self):
        response, _ = self.run_fixture("cold-es", operation="prepare-es")
        self.assertTrue(response["ok"])
        self.assertEqual(response["updates"], 2)
        self.assertFalse(response["shown"])
        response, _ = self.run_fixture("error-es")
        self.assertFalse(response["ok"])
        self.assertIn("Cierra Darkwatch", response["message"])
        self.assertIn("importar o reparar", response["message"])

    def test_asset_update_progress_uses_general_preparation_title(self):
        for mode in ("update", "update-es"):
            with self.subTest(mode=mode):
                response, _ = self.run_fixture(mode, operation=mode)
                self.assertTrue(response["ok"])
                self.assertEqual(response["updates"], 2)
                self.assertFalse(response["shown"])

    def test_cancel_from_preparation_view_reaches_backend_and_does_not_report_success(self):
        for operation in ("cancel", "close"):
            with self.subTest(operation=operation):
                response, record = self.run_fixture("cancel", operation=operation)
                self.assertFalse(response["ok"])
                self.assertTrue(response["cancelled"])
                self.assertEqual(response["cancels"], 1)
                details = json.loads(record.read_text(encoding="utf-8-sig"))
                self.assertEqual(details["args"][-2], "--cancel-file")
                self.assertFalse(Path(details["args"][-1]).exists())

    def test_missing_helper_files_fail_before_process_start(self):
        for missing in ["python", "backend"]:
            with self.subTest(missing=missing):
                package = self.build / ("missing " + missing)
                helper = package / "payload/python/python.exe"
                helper.parent.mkdir(parents=True)
                if missing != "python":
                    shutil.copyfile(self.helper, helper)
                if missing != "backend":
                    (package / "payload/setup_backend.py").write_text("# fixture\n", encoding="utf-8")
                response, _ = self.run_fixture("missing-" + missing, package=package)
                self.assertFalse(response["ok"])
                self.assertEqual(response["type"], "System.IO.IOException")
                self.assertIn("Extract the complete", response["message"])

    def test_production_winexe_entry_success_does_not_show_launcher(self):
        data = self.production.read_bytes()
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        self.assertEqual(data[pe:pe + 4], b"PE\0\0")
        self.assertEqual(struct.unpack_from("<H", data, pe + 24 + 68)[0], 2, "Direct start must use Windows GUI subsystem")
        record = self.evidence / "shipping-entry.json"
        environment = dict(os.environ, DARKWATCH_DIRECT_FIXTURE_MODE="success",
                           DARKWATCH_DIRECT_FIXTURE_REPORT=str(record))
        result = subprocess.run([str(self.production)], capture_output=True, env=environment, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout + result.stderr, b"")
        details = json.loads(record.read_text(encoding="utf-8-sig"))
        self.assertEqual(details["args"][6], "--play")
        self.assertEqual(details["args"][-2], "--cancel-file")
        self.assertFalse(Path(details["args"][-1]).exists())
        self.assertEqual(Path(details["args"][3]), self.build)
        self.assertEqual(Path(details["args"][5]), self.build / "GameData")
        self.results["production_entry_fixture_passed"] = True

    def test_production_entry_follows_a_moved_portable_folder(self):
        original = self.build.parent / "before move"
        (original / "payload/python").mkdir(parents=True)
        shutil.copyfile(self.production, original / self.production.name)
        shutil.copyfile(self.helper, original / "payload/python/python.exe")
        shutil.copyfile(self.backend, original / "payload/setup_backend.py")
        (original / "GameData").mkdir()
        (original / "GameData/player-save.fixture").write_bytes(b"preserved fixture only")
        moved = self.build.parent / "moved portable folder 日本語 🦇"
        original.rename(moved)
        self.assertFalse(original.exists())
        record = self.evidence / "moved-entry.json"
        environment = dict(os.environ, DARKWATCH_DIRECT_FIXTURE_MODE="success",
                           DARKWATCH_DIRECT_FIXTURE_REPORT=str(record))
        result = subprocess.run([str(moved / self.production.name)], capture_output=True, env=environment, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout + result.stderr, b"")
        details = json.loads(record.read_text(encoding="utf-8-sig"))
        self.assertEqual(Path(details["args"][3]), moved)
        self.assertEqual(Path(details["args"][5]), moved / "GameData")
        self.assertEqual(Path(details["cwd"]), moved)
        self.assertEqual((moved / "GameData/player-save.fixture").read_bytes(), b"preserved fixture only")
        self.results["moved_portable_entry_passed"] = True


if __name__ == "__main__":
    unittest.main()
