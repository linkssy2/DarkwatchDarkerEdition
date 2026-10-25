"""Compile the real WPF launcher and test it without showing UI or running the game.

The helper process is a tiny C# protocol fixture, never the installation backend.
Set DARKWATCH_LAUNCHER_UI_EVIDENCE to retain rendered previews and harness output.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319"
REFERENCES = ["System.dll", "System.Core.dll", "System.Xaml.dll", "System.Web.Extensions.dll",
              "WPF/PresentationFramework.dll", "WPF/PresentationCore.dll", "WPF/WindowsBase.dll"]

HELPER = r'''
using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
class ProtocolFixture {
    static int Main(string[] args) {
        Console.OutputEncoding = new UTF8Encoding(false);
        string token = null;
        for (int i=0; i<args.Length-1; ++i) if(args[i]=="--cancel-file") token=args[i+1];
        if(args.Length<7 || args[0]!="-B" || !File.Exists(args[1])) return 9;
        string mode=Environment.GetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE");
        Console.WriteLine("not a JSON event");
        Console.WriteLine("null");
        Console.WriteLine("{\"event\":\"progress\",\"message\":\"Preparing HD menus…\",\"percent\":35}");
        if(mode=="cancel") {
            for(int n=0; n<300 && !File.Exists(token); ++n) Thread.Sleep(10);
            if(!File.Exists(token)) return 10;
            Console.WriteLine("{\"event\":\"error\",\"message\":\"Canceled safely\",\"cancelled\":true,\"ready\":false}");
            return 1;
        }
        if(mode=="locked") Thread.Sleep(150);
        if(mode=="error") { Console.Error.Write(new string('E',700)); return 2; }
        if(mode=="hd") {
            int at=Array.IndexOf(args,"--install-hd-textures");
            if(at<0||at+1>=args.Length||args[at+1]!=@"C:\Downloads\Darkwatch HD 🦇.zip") return 11;
            Console.WriteLine("{\"event\":\"result\",\"message\":\"HD fixture installed\",\"percent\":100,\"installed\":true,\"ready\":true,\"hd_textures_installed\":true}");
            return 0;
        }
        if(mode=="spanish") {
            int at=Array.IndexOf(args,"--install-spanish");
            if(at<0||at+1>=args.Length||args[at+1]!=@"C:\Downloads\Español 🦇.zip") return 12;
            Console.WriteLine("{\"event\":\"result\",\"message\":\"Spanish fixture installed\",\"installed\":true,\"ready\":true,\"spanish_installed\":true,\"language\":\"en\"}");
            return 0;
        }
        if(mode=="language-es"||mode=="language-en") {
            int at=Array.IndexOf(args,"--set-language");
            string language=mode.Substring(9);
            if(at<0||at+1>=args.Length||args[at+1]!=language) return 13;
            Console.WriteLine("{\"event\":\"result\",\"message\":\"Language fixture changed\",\"installed\":true,\"ready\":true,\"spanish_installed\":true,\"language\":\""+language+"\"}");
            return 0;
        }
        Console.WriteLine("{\"event\":\"result\",\"message\":\"Verified fixture only\",\"percent\":100,\"installed\":true,\"ready\":true,\"install_dir\":\"C:\\\\Fixture\\\\Active\"}");
        return 0;
    }
}
'''

HARNESS = r'''
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using DarkwatchDarkerEdition;

class LauncherUiHarness {
    const BindingFlags Private = BindingFlags.NonPublic | BindingFlags.Instance;
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static readonly Dictionary<string,object> Evidence = new Dictionary<string,object>();
    static void Check(bool result, string reason) { if(!result) throw new Exception(reason); }
    static T Element<T>(Launcher l,string name) where T:FrameworkElement {
        var element=l.Window.FindName(name) as T;
        Check(element!=null,"Missing XAML element "+name); return element;
    }
    static object Field(Launcher l,string name) { return typeof(Launcher).GetField(name,Private).GetValue(l); }
    static object Call(Launcher l,string name,params object[] args) {
        return typeof(Launcher).GetMethod(name,Private).Invoke(l,args);
    }
    static void State(Launcher l,Dictionary<string,object> state) { Call(l,"ApplyState",state); }
    static void Pump(Func<bool> complete) {
        var frame=new DispatcherFrame(); var watch=Stopwatch.StartNew();
        var timer=new DispatcherTimer(DispatcherPriority.Background);
        timer.Interval=TimeSpan.FromMilliseconds(10);
        timer.Tick+=delegate { if(complete()||watch.ElapsedMilliseconds>8000) frame.Continue=false; };
        timer.Start(); Dispatcher.PushFrame(frame); timer.Stop();
        Check(complete(),"Isolated helper did not finish within eight seconds");
    }
    static void Finish(Task task) { Pump(()=>task.IsCompleted); task.GetAwaiter().GetResult(); }
    static Task Run(Launcher l,string action) { return (Task)Call(l,"Run",action,null); }
    static void Click(Launcher l,string name) { Element<Button>(l,name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); }
    static void Idle(Launcher l) {
        Check(!(bool)Field(l,"busy"),"Operation left launcher busy");
        Check(Field(l,"cancelFile")==null,"Private cancellation token retained");
        Check(Element<Button>(l,"ImportButton").IsEnabled,"Import did not recover");
        Check(Element<Button>(l,"CancelButton").Visibility==Visibility.Collapsed,"Cancel remained visible");
        Check(!Element<ProgressBar>(l,"Progress").IsIndeterminate,"Progress remained indeterminate");
        Check(!l.Window.IsVisible,"Test unexpectedly showed a window");
    }

    static void Quote() {
        string[] cases={"", "plain", "space and tab\t", "C:\\with space\\", "ends\\\\", "a\"quoted\"value", "before\\\"after", "\\\"", "line\nfeed", "& | < > ^ % ! $() `", "日本語 é 🦇"};
        var info=new ProcessStartInfo(Assembly.GetExecutingAssembly().Location,
            "--echo-args "+String.Join(" ",cases.Select(SetupProcess.Quote))) {
            UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,
            StandardOutputEncoding=Encoding.UTF8
        };
        using(var process=Process.Start(info)) {
            var actual=Json.Deserialize<string[]>(process.StandardOutput.ReadToEnd());
            process.WaitForExit(); Check(process.ExitCode==0,"Argument echo failed");
            Check(cases.SequenceEqual(actual),"Windows argument quoting changed a value");
        }
        Evidence["round_trip_arguments"]=cases.Length;
    }

    static void ResourcesAndState() {
        Check(Launcher.DiscImageFilter=="Xbox disc images (*.iso;*.xiso)|*.iso;*.xiso","ISO/XISO picker filter changed");
        Check(Launcher.TexturePackFilter=="Darker Edition HD texture pack (*.zip;*.zip.001)|*.zip;*.zip.001","HD pack picker filter mismatch");
        Evidence["iso_xiso_picker"]=true;
        var l=new Launcher(true);
        Check((string)Field(l,"installRoot")==Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"GameData"),"Launcher installation is not portable beside its executable");
        Evidence["portable_install_root"]=true;
        foreach(string name in new[]{"Cover","Insignia","SmallInsignia"}) {
            var image=Element<Image>(l,name).Source as BitmapSource;
            Check(image!=null&&image.PixelWidth>0&&image.PixelHeight>0,"Missing embedded image "+name);
        }
        Check(Element<Button>(l,"ImportButton").IsEnabled,"Fresh import disabled");
        foreach(string name in new[]{"PlayButton","VerifyButton","FolderButton","TextureButton","SpanishButton"})
            Check(!Element<Button>(l,name).IsEnabled,"Fresh "+name+" enabled");
        Check(!Element<ComboBox>(l,"LanguageChoice").IsEnabled&&!Element<ComboBoxItem>(l,"SpanishChoice").IsEnabled,"Fresh language controls enabled");
        State(l,new Dictionary<string,object>{{"installed",true},{"ready",true},{"install_dir",@"C:\Fixture\Version"},{"message","Ready – fixture"},{"percent",120}});
        Check((string)Field(l,"gameDirectory")==@"C:\Fixture\Version","Backend install_dir was ignored");
        Check(Element<TextBlock>(l,"StatusText").Text=="Ready – fixture","Unicode status changed");
        Check(Element<TextBlock>(l,"StateTitle").Text=="THE NIGHT AWAITS","Ready title mismatch");
        Check(Element<ProgressBar>(l,"Progress").Value==100,"Progress exceeds maximum");
        foreach(string name in new[]{"PlayButton","VerifyButton","FolderButton","TextureButton"})
            Check(Element<Button>(l,name).IsEnabled,"Ready "+name+" disabled");
        Check(Element<TextBlock>(l,"TextureStatus").Text.Contains("not installed"),"Absent optional pack label missing");
        State(l,new Dictionary<string,object>{{"hd_textures_installed",true}});
        Check((string)Element<Button>(l,"TextureButton").Content=="REINSTALL HD TEXTURES","Installed pack state missing");
        Check(Element<TextBlock>(l,"TextureStatus").Text.Contains("Toggle in Graphics"),"Installed pack hint missing");
        Check((string)Element<Button>(l,"ImportButton").Content=="IMPORT / REPAIR","Repair action missing");
        State(l,new Dictionary<string,object>{{"ready",false},{"percent",-3}});
        Check(!Element<Button>(l,"PlayButton").IsEnabled&&Element<Button>(l,"VerifyButton").IsEnabled,"Damaged state loses installed/ready separation");
        Check(!Element<Button>(l,"TextureButton").IsEnabled,"HD install should require a ready base game");
        Check(Element<ProgressBar>(l,"Progress").Value==0,"Progress below minimum");
        Check(!l.Window.IsVisible,"State checks showed a window");
        State(l,new Dictionary<string,object>{{"event","shader_prepare"},{"message","Preparing shaders — 1 of 4"},{"percent",25}});
        Check(Element<TextBlock>(l,"StateTitle").Text=="PREPARING SHADERS","Shader phase title missing");
        Check(Element<ProgressBar>(l,"Progress").Value==25&&!Element<ProgressBar>(l,"Progress").IsIndeterminate,"Shader progress must be real work");
        Click(l,"MinimizeButton");
        Check(l.Window.WindowState==WindowState.Minimized&&!l.Window.IsVisible,"Minimize click failed or showed UI");
        Click(l,"CloseButton");
        Check(!l.Window.IsVisible,"Close click showed UI");
        Evidence["resource_state_contract"]=true;
    }

    static void ProcessEvents() {
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","success");
        var l=new Launcher(true); var task=Run(l,"--status");
        Check((bool)Field(l,"busy"),"Status never entered busy state");
        Check(Field(l,"cancelFile")==null,"Read-only status unexpectedly created cancel token");
        Finish(task); Idle(l);
        Check((bool)Field(l,"ready")&&(bool)Field(l,"installed"),"Helper result did not publish readiness");
        Check(Element<TextBlock>(l,"StatusText").Text=="Verified fixture only","Helper event not displayed");
        Check(((string)Field(l,"gameDirectory")).EndsWith("Active"),"Helper install directory ignored");
        Click(l,"VerifyButton");
        Check((bool)Field(l,"busy"),"Verify button did not start operation");
        foreach(string name in new[]{"ImportButton","PlayButton","VerifyButton","FolderButton","TextureButton"})
            Check(!Element<Button>(l,name).IsEnabled,"Busy "+name+" enabled");
        string token=(string)Field(l,"cancelFile");
        Check(token!=null&&!File.Exists(token),"Cancellation was requested without a click");
        Pump(()=>!(bool)Field(l,"busy")); Idle(l);
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","error");
        Finish(Run(l,"--verify")); Idle(l);
        Check(Element<TextBlock>(l,"StatusText").Text==new string('E',500),"Helper stderr not capped/displayed");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","hd");
        Finish((Task)Call(l,"Run","--install-hd-textures",@"C:\Downloads\Darkwatch HD 🦇.zip")); Idle(l);
        Check((bool)Field(l,"hdTexturesInstalled")&&Element<Button>(l,"PlayButton").IsEnabled,"Optional install result lost base readiness");
        Check((string)Element<Button>(l,"TextureButton").Content=="REINSTALL HD TEXTURES","Optional installer result did not refresh action");
        Evidence["optional_pack_protocol_and_state"]=true;
        Evidence["real_helper_and_verify_event"]=true;
    }

    static void Cancellation() {
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","cancel");
        var l=new Launcher(true);var task=Run(l,"--import-iso");
        string token=(string)Field(l,"cancelFile");
        Check(token!=null,"Import missing cancellation token");
        Check(Element<Button>(l,"CancelButton").Visibility==Visibility.Visible,"Cancel not exposed while importing");
        Click(l,"CancelButton");
        Check(File.Exists(token),"Cancel button did not signal helper");
        Check(!Element<Button>(l,"CancelButton").IsEnabled,"Cancel button did not acknowledge request");
        Finish(task); Idle(l);
        Check(!File.Exists(token),"Cancellation token was not removed");
        Check(Element<TextBlock>(l,"StatusText").Text=="Canceled safely","Cancellation result lost");
        Check(!(bool)Field(l,"ready"),"Canceled import became playable");

        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","locked");
        task=Run(l,"--verify");string lockedToken=(string)Field(l,"cancelFile");
        Check(lockedToken!=token,"Operations reused cancellation token");
        using(var held=new FileStream(lockedToken,FileMode.Create,FileAccess.ReadWrite,FileShare.None)) {
            Finish(task); Idle(l);
        }
        File.Delete(lockedToken);
        Check((bool)Field(l,"ready"),"Successful verify was lost after cleanup failure");
        Evidence["cancel_event_and_locked_token_recovery"]=true;
    }

    static void Language() {
        Check(Launcher.SpanishPackFilter=="Darker Edition Spanish pack (*.zip)|*.zip","Spanish picker accepts unexpected formats");
        var l=new Launcher(true);
        State(l,new Dictionary<string,object>{{"installed",true},{"ready",true},{"language","en"},{"spanish_installed",false}});
        Check(Element<Button>(l,"SpanishButton").IsEnabled,"Ready game cannot install Spanish");
        Check(Element<ComboBox>(l,"LanguageChoice").IsEnabled&&!Element<ComboBoxItem>(l,"SpanishChoice").IsEnabled,"Missing pack must disable Spanish only");
        Element<ComboBox>(l,"LanguageChoice").SelectedIndex=1;
        Check(Element<ComboBox>(l,"LanguageChoice").SelectedIndex==0&&!(bool)Field(l,"busy"),"Missing pack selection reached backend");
        State(l,new Dictionary<string,object>{{"spanish_installed",true},{"spanish_audio_installed",false}});
        Check(Element<ComboBoxItem>(l,"SpanishChoice").IsEnabled,"Bundled Spanish requires an optional download");
        Check((string)Element<Button>(l,"SpanishButton").Content=="SPANISH VOICES","Text availability incorrectly implies voices installed");
        Check(Element<TextBlock>(l,"LanguageStatus").Text.Contains("Text and subtitles included"),"Included translation is not explained");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","language-es");
        Element<ComboBox>(l,"LanguageChoice").SelectedIndex=1;
        Pump(()=>!(bool)Field(l,"busy")); Idle(l);
        Check((string)Field(l,"language")=="es","Bundled Spanish could not be selected before voice import");
        Evidence["builtin_spanish_without_voice_download"]=true;
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","spanish");
        Finish((Task)Call(l,"Run","--install-spanish",@"C:\Downloads\Español 🦇.zip")); Idle(l);
        Check(Element<ComboBoxItem>(l,"SpanishChoice").IsEnabled,"Installed Spanish still disabled");
        State(l,new Dictionary<string,object>{{"language","es"},{"spanish_installed",true}});
        Check(!(bool)Field(l,"busy")&&Element<ComboBox>(l,"LanguageChoice").SelectedIndex==1,"Programmatic language refresh started an operation");
        Check((string)Element<Button>(l,"PlayButton").Content=="JUGAR","Spanish action missing");
        Check(Element<TextBlock>(l,"StateTitle").Text=="LA NOCHE TE ESPERA","Spanish title missing");
        Check(Element<TextBlock>(l,"DiscFeatures").Text.Contains("Ratón"),"Spanish accent lost");
        foreach(var example in new[]{
            new[]{"Preparing shaders — 12 of 4440","Preparando shaders — 12 de 4440"},
            new[]{"Verifying data/audioDlg.pck","Verificando data/audioDlg.pck"},
            new[]{"Importing Movies1.pck","Importando Movies1.pck"},
            new[]{"Instalación verificada.","Instalación verificada."}}) {
            Check(Launcher.Localize(example[0],"es")==example[1],"Translated progress changed a filename, count or Spanish text");
            Check(Launcher.Localize(example[0],"en")==example[0],"English progress changed");
        }
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","language-en");
        Element<ComboBox>(l,"LanguageChoice").SelectedIndex=0;
        Check((bool)Field(l,"busy")&&!Element<ComboBox>(l,"LanguageChoice").IsEnabled,"User selection did not lock language controls");
        Pump(()=>!(bool)Field(l,"busy")); Idle(l);
        Check((string)Field(l,"language")=="en"&&(string)Element<Button>(l,"PlayButton").Content=="PLAY","English switch did not restore copy");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","error");
        Element<ComboBox>(l,"LanguageChoice").SelectedIndex=1;
        Pump(()=>!(bool)Field(l,"busy")); Idle(l);
        Check((string)Field(l,"language")=="en"&&Element<ComboBox>(l,"LanguageChoice").SelectedIndex==0,"Failed language change was retained");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","language-es");
        Element<ComboBox>(l,"LanguageChoice").SelectedIndex=1;
        Pump(()=>!(bool)Field(l,"busy")); Idle(l);
        Check((string)Field(l,"language")=="es","User Spanish selection was not applied");
        var preparation=Launcher.Preparing(()=>{});
        preparation.UpdatePreparation(new Dictionary<string,object>{{"event","shader_prepare"},{"language","es"},{"message","Preparando shaders"}});
        Check(Element<TextBlock>(preparation,"StateTitle").Text=="PREPARANDO SHADERS","Direct preparation stayed English");
        Check(Element<StackPanel>(preparation,"LanguageActions").Visibility==Visibility.Collapsed,"Preparation exposed language mutations");
        Evidence["language_selection_install_rollback_and_no_reentrancy"]=true;
    }

    static void Preview(string destination) {
        Directory.CreateDirectory(destination);
        foreach(string state in new[]{"fresh","ready","hd-installed","importing","shaders","spanish-ready","spanish-shaders"}) {
            var l=state.EndsWith("shaders")?Launcher.Preparing(()=>{}):new Launcher(true);string path=Path.Combine(destination,"launcher-"+state+".png");
            Call(l,"FitToWorkArea",new Rect(0,0,1920,1080));
            l.RenderPreview(path,state);
            Check(!l.Window.IsVisible,"Preview showed a desktop window");
            BitmapFrame frame;
            using(var stream=File.OpenRead(path)) frame=BitmapFrame.Create(stream,BitmapCreateOptions.PreservePixelFormat,BitmapCacheOption.OnLoad);
            Check(frame.PixelWidth==1060&&frame.PixelHeight==720,"Preview dimensions changed");
            var image=new FormatConvertedBitmap(frame,System.Windows.Media.PixelFormats.Bgra32,null,0);
            byte[] pixels=new byte[1060*720*4];image.CopyPixels(pixels,1060*4,0);
            int opaque=0,bright=0;var colors=new HashSet<int>();
            for(int i=0;i<pixels.Length;i+=4) {
                if(pixels[i+3]>240) ++opaque;
                if(pixels[i]+pixels[i+1]+pixels[i+2]>400&&pixels[i+3]>240) ++bright;
                colors.Add(pixels[i]|pixels[i+1]<<8|pixels[i+2]<<16|pixels[i+3]<<24);
            }
            Check(opaque>700000&&bright>20000&&colors.Count>2000,"Blank or incomplete offscreen preview: "+state);
            Evidence["preview_"+state]=new {width=frame.PixelWidth,height=frame.PixelHeight,opaque=opaque,bright=bright,colors=colors.Count};
        }
    }

    static void ReleaseAndSmallDesktop(string release) {
        var type=Assembly.LoadFile(release).GetType("DarkwatchDarkerEdition.Launcher");
        Check(type.GetMethod("RenderPreview")==null,"Release launcher exposes preview diagnostics");
        Check(type.GetConstructors().All(c=>c.GetParameters().Length==0),"Release launcher accepts testing mode");
        foreach(var area in new[]{new Rect(0,0,1280,680),new Rect(0,0,960,520),new Rect(0,0,800,560)}) {
            var l=new Launcher(true);Call(l,"FitToWorkArea",area);
            Check(l.Window.Width<=area.Width-24&&l.Window.Height<=area.Height-24,"Launcher exceeds desktop work area");
            var content=(FrameworkElement)l.Window.Content;
            content.Measure(new Size(l.Window.Width,l.Window.Height));
            content.Arrange(new Rect(0,0,l.Window.Width,l.Window.Height));content.UpdateLayout();
            foreach(string name in new[]{"ImportButton","PlayButton","VerifyButton","FolderButton","TextureButton","SpanishButton","CloseButton"}) {
                var button=Element<Button>(l,name);
                var bounds=button.TransformToAncestor(content).TransformBounds(new Rect(new Point(0,0),button.RenderSize));
                Check(bounds.Left>=0&&bounds.Top>=0&&bounds.Right<=l.Window.Width+1&&bounds.Bottom<=l.Window.Height+1,
                      "Clipped launcher button "+name+" on small/high-DPI desktop");
            }
            var notice=Element<TextBlock>(l,"DiscNotice").TransformToAncestor(content).TransformBounds(new Rect(new Point(),Element<TextBlock>(l,"DiscNotice").RenderSize));
            var status=Element<TextBlock>(l,"StatusText").TransformToAncestor(content).TransformBounds(new Rect(new Point(),Element<TextBlock>(l,"StatusText").RenderSize));
            Check(notice.Bottom<status.Top,"Optional language controls overlap launcher description");
            Check(!l.Window.IsVisible,"Small desktop check showed a window");
        }
        Evidence["release_preview_api_absent"]=true;
        Evidence["scaled_workareas_checked"]=3;
    }

    [STAThread] static int Main(string[] args) {
        Console.OutputEncoding=new UTF8Encoding(false);
        if(args.Length>0&&args[0]=="--echo-args") {Console.Write(Json.Serialize(args.Skip(1).ToArray()));return 0;}
        try {
            var app=new Application {ShutdownMode=ShutdownMode.OnExplicitShutdown};
            SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext());
            Quote(); ResourcesAndState(); ProcessEvents(); Cancellation(); Language(); Preview(args[0]); ReleaseAndSmallDesktop(args[1]);
            Evidence["shown_windows"]=0; Evidence["real_backend_or_game_started"]=false;
            Console.WriteLine(Json.Serialize(Evidence)); return 0;
        } catch(Exception ex) {Console.Error.WriteLine(ex);return 1;}
    }
}
'''


@unittest.skipUnless(os.name == "nt" and (FRAMEWORK / "csc.exe").exists(), "Requires Windows .NET Framework WPF")
class LauncherUiTests(unittest.TestCase):
    def test_actual_wpf_resources_events_process_and_offscreen_render(self):
        with tempfile.TemporaryDirectory(prefix="darkwatch-launcher-ui-") as directory:
            build = Path(directory)
            evidence = Path(os.environ.get("DARKWATCH_LAUNCHER_UI_EVIDENCE", build / "evidence"))
            evidence.mkdir(parents=True, exist_ok=True)
            helper = build / "payload/python/python.exe"
            helper.parent.mkdir(parents=True)
            (build / "payload/setup_backend.py").write_text("# Protocol fixture only. Never executed.\n", encoding="utf-8")
            (build / "ProtocolFixture.cs").write_text(HELPER, encoding="utf-8")
            (build / "Harness.cs").write_text(HARNESS, encoding="utf-8")
            compiler = str(FRAMEWORK / "csc.exe")
            def compile_cs(arguments):
                result = subprocess.run([compiler, "/nologo", "/target:exe", "/platform:x64", *arguments], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            compile_cs([f"/reference:{FRAMEWORK / 'System.Web.Extensions.dll'}", f"/out:{helper}", str(build / "ProtocolFixture.cs")])
            executable = build / "LauncherUiHarness.exe"
            references = [f"/reference:{FRAMEWORK / name}" for name in REFERENCES]
            resources = [f"/resource:{ROOT / 'launcher' / path},{name}" for path, name in [
                ("MainWindow.xaml", "Darkwatch.MainWindow.xaml"), ("assets/cover-darker-edition.png", "Darkwatch.Cover.png"),
                ("assets/insignia.png", "Darkwatch.Insignia.png")]]
            production = build / "Darkwatch Darker Edition.exe"
            sources = [str(ROOT / "launcher" / name) for name in ["Launcher.cs", "SetupProcess.cs"]]
            compile_cs([*references, *resources, f"/out:{production}", *sources])
            compile_cs([*references, *resources, "/define:LAUNCHER_TESTING", "/main:LauncherUiHarness", f"/out:{executable}", *sources, str(build / "Harness.cs")])
            result = subprocess.run([str(executable), str(evidence), str(production)], capture_output=True, encoding="utf-8-sig", timeout=35)
            (evidence / "harness.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            report["source_sha256"] = {name: hashlib.sha256((ROOT / "launcher" / name).read_bytes()).hexdigest() for name in ["Launcher.cs", "SetupProcess.cs", "MainWindow.xaml", "assets/cover-darker-edition.png", "assets/insignia.png"]}
            (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            self.assertTrue(report["cancel_event_and_locked_token_recovery"])
            self.assertEqual(report["shown_windows"], 0)
            self.assertFalse(report["real_backend_or_game_started"])
            self.assertTrue(report["release_preview_api_absent"])
            self.assertEqual(report["scaled_workareas_checked"], 3)


if __name__ == "__main__":
    unittest.main()
