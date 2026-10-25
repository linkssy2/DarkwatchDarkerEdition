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
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319"
REFERENCES = ["System.dll", "System.Core.dll", "System.Web.Extensions.dll", "System.Xaml.dll",
              "WPF/PresentationFramework.dll", "WPF/PresentationCore.dll", "WPF/WindowsBase.dll"]

HELPER = r'''
using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
class DirectPlayFixture {
    static int Main(string[] args) {
        Console.OutputEncoding=new UTF8Encoding(false);
        string mode=Environment.GetEnvironmentVariable("DARKWATCH_DIRECT_FIXTURE_MODE");
        var json=new JavaScriptSerializer();
        File.WriteAllText(Environment.GetEnvironmentVariable("DARKWATCH_DIRECT_FIXTURE_REPORT"),
            json.Serialize(new {args=args,cwd=Environment.CurrentDirectory,
                encoding=Environment.GetEnvironmentVariable("PYTHONIOENCODING")}),Encoding.UTF8);
        Console.WriteLine("not JSON"); Console.WriteLine("null");
        if(mode=="cold-es"||mode=="error-es") Console.WriteLine("{\"event\":\"status\",\"language\":\"es\"}");
        Console.WriteLine("{\"event\":\"progress\",\"percent\":100}");
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
            if(args[0]=="info") {
                var info=SetupProcess.Create(args[1],args[2],"--play");
                Console.Write(json.Serialize(new {file=info.FileName,arguments=info.Arguments,
                    cwd=info.WorkingDirectory,shell=info.UseShellExecute,hidden=info.CreateNoWindow,
                    stdout=info.RedirectStandardOutput,stderr=info.RedirectStandardError,
                    outcode=info.StandardOutputEncoding.CodePage,errcode=info.StandardErrorEncoding.CodePage,
                    encoding=info.EnvironmentVariables["PYTHONIOENCODING"]}));
            } else if(args[0]=="prepare"||args[0]=="prepare-es"||args[0]=="cancel"||args[0]=="close") {
                int updates=0,cancels=0;Launcher view=null;
                string token=Path.Combine(args[2],".cancel-fixture");Directory.CreateDirectory(args[2]);
                try {
                    DirectPlay.Run(args[1],args[2],item=>{
                        ++updates;
                        if(view==null)view=Launcher.Preparing(()=>{++cancels;File.WriteAllText(token,"cancel");});
                        view.UpdatePreparation(item);
                        if(view.Window.IsVisible)throw new Exception("Preparation fixture showed a window");
                        if(((TextBlock)view.Window.FindName("StateTitle")).Text!=(args[0]=="prepare-es"?"PREPARANDO SHADERS":"PREPARING SHADERS"))throw new Exception("Missing preparation title");
                        if(args[0]=="prepare-es"&&!((TextBlock)view.Window.FindName("StatusText")).Text.StartsWith("Preparando shaders — "))throw new Exception("Shader progress stayed English");
                        if(((Grid)view.Window.FindName("LaunchActions")).Visibility!=Visibility.Collapsed)throw new Exception("Preparation exposes launch actions");
                        if(((StackPanel)view.Window.FindName("LanguageActions")).Visibility!=Visibility.Collapsed)throw new Exception("Preparation exposes language mutation");
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
        cls.results = {"real_backend_or_game_started": False, "fixture_results": {},
                       "source_sha256": {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources}}

    @classmethod
    def tearDownClass(cls):
        (cls.evidence / "report.json").write_text(json.dumps(cls.results, indent=2) + "\n", encoding="utf-8")
        cls.temp.cleanup()

    def run_fixture(self, mode="success", operation="run", package=None):
        record = self.evidence / f"{mode}-{operation}.json"
        environment = dict(os.environ, DARKWATCH_DIRECT_FIXTURE_MODE=mode,
                           DARKWATCH_DIRECT_FIXTURE_REPORT=str(record))
        result = subprocess.run([str(self.harness), operation, str(package or self.build), str(self.install)],
                                capture_output=True, encoding="utf-8-sig", env=environment, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(result.stderr, result.stderr)
        response = json.loads(result.stdout)
        self.results["fixture_results"][mode + "-" + operation] = response
        return response, record

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
