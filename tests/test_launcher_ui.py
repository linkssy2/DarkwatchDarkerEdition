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
REFERENCES = ["System.dll", "System.Core.dll", "System.Xaml.dll", "System.Web.Extensions.dll", "System.Windows.Forms.dll",
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
        string actions=Environment.GetEnvironmentVariable("DARKWATCH_UI_ACTIONS");
        if(actions!=null) {
            for(int attempt=0;;++attempt) {
                try {File.AppendAllText(actions,args[6]+"\n");break;}
                catch(IOException) {if(attempt>=20)throw;Thread.Sleep(10);}
            }
        }
        if(Array.IndexOf(args,"--check-updates")>=0) {
            if(token!=null) return 17;
            string calls=Environment.GetEnvironmentVariable("DARKWATCH_UI_RELEASE_CALLS");
            if(calls!=null) File.AppendAllText(calls,"check\n");
            Thread.Sleep(150);
            string release=Environment.GetEnvironmentVariable("DARKWATCH_UI_RELEASE_MODE")??"unavailable";
            if(release=="failure") {Console.Error.Write("Fixture network unavailable");return 1;}
            var json=new JavaScriptSerializer();
            string url=release=="malicious"?"https://github.com/other/repo/releases/tag/v0.7":"https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7";
            Console.WriteLine("{\"event\":\"progress\",\"message\":\"Must not replace installation status\",\"percent\":2}");
            Console.WriteLine(json.Serialize(new { @event="release_check",status=release=="malicious"?"available":release,
                current_version="0.6.1",latest_version="0.7",release_url=url,message="Fixture release state"}));
            return 0;
        }
        string mode=Environment.GetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE");
        if(mode!=null&&mode.StartsWith("drop-")) {
            if(Array.IndexOf(args,"--status")>=0) {
                Console.WriteLine("{\"event\":\"status\",\"message\":\"Drop-in fixture status\",\"installed\":"+(mode=="drop-installed"?"true":"false")+",\"ready\":false}");
                return mode=="drop-status-failure"?1:0;
            }
            int at=Array.IndexOf(args,"--use-iso");
            if(at<0||at+1>=args.Length||args[at+1]!=Environment.GetEnvironmentVariable("DARKWATCH_UI_DROP_ISO")||token==null) return 21;
            Console.WriteLine("{\"event\":\"progress\",\"message\":\"Preparing drop-in resources\",\"percent\":42}");
            Thread.Sleep(150);
            if(mode=="drop-unsupported") {
                Console.WriteLine("{\"event\":\"error\",\"message\":\"Unsupported disc image. Choose the supported Xbox disc.\",\"ready\":false}");return 1;
            }
            Console.WriteLine("{\"event\":\"result\",\"message\":\"Drop-in ready\",\"installed\":true,\"ready\":true,\"source_mode\":\"iso\"}");return 0;
        }
        if(Array.IndexOf(args,"--download-update")>=0) {
            int at=Array.IndexOf(args,"--launcher-pid"),pid;
            if(at<0||at+1>=args.Length||!Int32.TryParse(args[at+1],out pid)||pid<=0||token==null)return 18;
            if(mode=="download") {
                Console.WriteLine("{\"event\":\"progress\",\"message\":\"Downloading update fixture\",\"percent\":25}");
                Thread.Sleep(150);
                Console.WriteLine("{\"event\":\"release_ready\",\"message\":\"Update prepared. Restarting launcher.\",\"version\":\"0.7\"}");
                return 0;
            }
            if(mode=="download-failure") {
                Console.WriteLine("{\"event\":\"error\",\"message\":\"Download fixture failed\",\"ready\":false}");return 1;
            }
            if(mode=="download-missing") {
                Console.WriteLine("{\"event\":\"result\",\"message\":\"Incomplete fixture\",\"ready\":false}");return 0;
            }
        }
        if(mode=="startup-update") {
            if(Array.IndexOf(args,"--status")>=0) {
                Console.WriteLine("{\"event\":\"status\",\"message\":\"Local content update needed\",\"installed\":true,\"ready\":false,\"update_available\":true}");return 0;
            }
            if(Array.IndexOf(args,"--update")>=0) {
                Console.WriteLine("{\"event\":\"result\",\"message\":\"Local content updated\",\"installed\":true,\"ready\":true,\"update_available\":false}");return 0;
            }
            return 19;
        }
        if(mode=="startup-fresh") {
            Console.WriteLine("{\"event\":\"status\",\"message\":\"No installed data\",\"installed\":false,\"ready\":false,\"update_available\":false}");return 0;
        }
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
        if(mode=="attach") {
            int at=Array.IndexOf(args,"--use-installation");
            if(at<0||at+1>=args.Length||args[at+1]!=@"E:\My Games\Darkwatch Español 🦇\GameData") return 14;
            Console.WriteLine("{\"event\":\"result\",\"message\":\"Existing installation selected. Update game to continue.\",\"installed\":true,\"ready\":false,\"update_available\":true,\"install_dir\":\"E:\\\\Existing\\\\Active\"}");
            return 0;
        }
        if(mode=="update") {
            if(Array.IndexOf(args,"--update")<0||Array.IndexOf(args,"--import-iso")>=0) return 15;
            Console.WriteLine("{\"event\":\"result\",\"message\":\"Updated fixture only\",\"installed\":true,\"ready\":true,\"update_available\":false}");
            return 0;
        }
        if(mode=="direct-iso") {
            int at=Array.IndexOf(args,"--use-iso");
            if(at<0||at+1>=args.Length||args[at+1]!=@"E:\My Games\Darkwatch Español 🦇.xiso"||Array.IndexOf(args,"--import-iso")>=0) return 20;
            Console.WriteLine("{\"event\":\"result\",\"message\":\"ISO selected\",\"installed\":true,\"ready\":true,\"source_mode\":\"iso\",\"iso_available\":true}");
            return 0;
        }
        if(mode=="hd") {
            int at=Array.IndexOf(args,"--install-hd-textures");
            if(at<0||at+1>=args.Length||args[at+1]!=@"C:\Downloads\Darkwatch HD 🦇.zip") return 11;
            Console.WriteLine("{\"event\":\"result\",\"message\":\"HD fixture installed\",\"percent\":100,\"installed\":true,\"ready\":true,\"hd_textures_installed\":true}");
            return 0;
        }
        if(mode=="spanish-iso") {
            int at=Array.IndexOf(args,"--install-spanish");
            string path=@"C:\My Games\PS2 Español 🦇.iso";
            if(at<0||at+1>=args.Length||args[at+1]!=path) return 12;
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
using System.Windows.Input;
using System.Windows.Media;
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
    static bool Visible(FrameworkElement element) {
        for(DependencyObject current=element;current!=null && !(current is Window);current=VisualTreeHelper.GetParent(current)) {
            var view=current as FrameworkElement;
            if(view!=null&&view.Visibility!=Visibility.Visible)return false;
        }
        return true;
    }
    static bool Visible(Launcher l,string name) {return Visible(Element<FrameworkElement>(l,name));}
    static void Manage(Launcher l) {
        Check(Visible(l,"ManageButton")&&Element<Button>(l,"ManageButton").IsEnabled,"Manage is unreachable");
        Click(l,"ManageButton");
        Check(Visible(l,"ManagePanel")&&!Visible(l,"HomePanel"),"Manage did not replace home");
        Check(Visible(l,"BackButton")&&Element<Button>(l,"BackButton").IsEnabled,"Manage has no usable Back");
    }
    sealed class OffscreenSource : PresentationSource {
        public override Visual RootVisual {get;set;}
        public override bool IsDisposed {get{return false;}}
        protected override CompositionTarget GetCompositionTargetCore() {return null;}
    }
    static void Escape(Launcher l) {
        l.Window.RaiseEvent(new KeyEventArgs(Keyboard.PrimaryDevice,new OffscreenSource(),0,Key.Escape) {RoutedEvent=Keyboard.PreviewKeyDownEvent});
    }
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
        Check(Visible(l,"ImportButton")&&!Visible(l,"HomeExistingButton")&&(string)Element<Button>(l,"ImportButton").Content=="SELECT GAME","Fresh home lacks a simple source chooser");
        Check(!Visible(l,"ManagePanel")&&!Visible(l,"PlayButton"),"Fresh home contains management or Play actions");
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
        Check(Visible(l,"PlayButton")&&!Visible(l,"ImportButton")&&!Visible(l,"HomeExistingButton"),"Ready home is not focused on Play");
        State(l,new Dictionary<string,object>{{"ready",false},{"percent",-3}});
        Check(!Element<Button>(l,"PlayButton").IsEnabled&&Element<Button>(l,"VerifyButton").IsEnabled,"Damaged state loses installed/ready separation");
        Check(!Element<Button>(l,"TextureButton").IsEnabled,"HD install should require a ready base game");
        Check(Element<ProgressBar>(l,"Progress").Value==0,"Progress below minimum");
        Check(Visible(l,"ImportButton")&&Visible(l,"ManageButton"),"Damaged installation hides its repair route");
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

    static void SourceSelection() {
        var l=new Launcher(true);
        Click(l,"ImportButton");
        Check(Visible(l,"SourcePanel")&&!Visible(l,"HomePanel")&&!Visible(l,"ManagePanel"),"Select Game did not open source chooser");
        foreach(string name in new[]{"UseIsoButton","ExtractIsoButton","HomeExistingButton","SourceBackButton"})
            Check(Visible(l,name)&&Element<Button>(l,name).IsEnabled,"Source choice unavailable: "+name);
        Check(Element<TextBlock>(l,"UseIsoHint").Text.Contains("Keep the ISO"),"Direct ISO lifetime was not explained");
        Check(Element<TextBlock>(l,"ExtractIsoHint").Text.Contains("removed after setup"),"Import-once lifetime was not explained");
        Escape(l);
        Check(Visible(l,"HomePanel")&&!Visible(l,"SourcePanel"),"Source Escape did not restore home");
        Manage(l);Click(l,"RepairIsoButton");Click(l,"SourceBackButton");
        Check(Visible(l,"ManagePanel")&&!Visible(l,"SourcePanel"),"Source Back lost Manage origin");
        Click(l,"RepairIsoButton");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","direct-iso");
        Task job=(Task)Call(l,"Run","--use-iso",@"E:\My Games\Darkwatch Español 🦇.xiso");
        Check(!Visible(l,"SourcePanel")&&!Element<Button>(l,"UseIsoButton").IsEnabled,"Busy source switch allowed a second selection");
        Finish(job);Idle(l);
        Check((bool)Field(l,"ready")&&(string)Field(l,"sourceMode")=="iso"&&Visible(l,"PlayButton"),"Direct ISO did not return to Play");
        Check(!Visible(l,"SourcePanel")&&!Visible(l,"ManagePanel")&&Element<TextBlock>(l,"StateDescription").Text.Contains("Keep it in place"),"Ready direct ISO state lost source guidance");
        State(l,new Dictionary<string,object>{{"ready",false},{"iso_available",false},{"message","Selected ISO is missing"}});
        Check(!Element<Button>(l,"PlayButton").IsEnabled&&Visible(l,"ImportButton"),"Missing ISO has no source repair route");
        Click(l,"ImportButton");State(l,new Dictionary<string,object>{{"language","es"}});
        Check((string)Element<Button>(l,"UseIsoButton").Content=="USAR ISO DIRECTAMENTE"&&Element<TextBlock>(l,"ExtractIsoHint").Text.Contains("eliminar la ISO"),"Spanish source guidance missing");
        Escape(l);State(l,new Dictionary<string,object>{{"installed",true},{"ready",true},{"source_mode","extracted"}});
        Check((string)Field(l,"sourceMode")=="extracted"&&!Element<TextBlock>(l,"StateDescription").Text.Contains("ISO"),"Extracted install retained direct-ISO requirement");
        Evidence["source_chooser_direct_iso_import_once_existing_and_missing_disc"]=true;
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
        Manage(l);
        Check(Visible(l,"VerifyButton"),"Verification is hidden in Manage");
        Click(l,"VerifyButton");
        Check((bool)Field(l,"busy"),"Verify button did not start operation");
        foreach(string name in new[]{"ImportButton","PlayButton","VerifyButton","FolderButton","TextureButton","ExistingInstallButton","RepairIsoButton"})
            Check(!Element<Button>(l,name).IsEnabled,"Busy "+name+" enabled");
        string token=(string)Field(l,"cancelFile");
        Check(token!=null&&!File.Exists(token),"Cancellation was requested without a click");
        Pump(()=>!(bool)Field(l,"busy")); Idle(l);
        Check(Visible(l,"ManagePanel")&&(bool)Field(l,"manageOpen"),"Verification left the selected Manage panel");
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

    static void Navigation() {
        var l=new Launcher(true);
        Check(Visible(l,"HomePanel")&&!Visible(l,"ManagePanel"),"Fresh launcher does not open home");
        Manage(l);
        foreach(string name in new[]{"RepairIsoButton","ExistingInstallButton","VerifyButton","FolderButton","TextureButton","LanguageChoice","SpanishButton","CheckUpdatesButton"})
            Check(Visible(l,name),"Management control is unreachable: "+name);
        Check(!Visible(l,"ImportButton")&&!Visible(l,"PlayButton")&&!Visible(l,"HomeExistingButton"),"Manage retains home actions");
        Click(l,"BackButton");
        Check(Visible(l,"HomePanel")&&!Visible(l,"ManagePanel")&&!(bool)Field(l,"manageOpen"),"Back did not restore home");
        Manage(l);Escape(l);
        Check(Visible(l,"HomePanel")&&!Visible(l,"ManagePanel")&&!(bool)Field(l,"windowClosed"),"Escape failed to return home safely");
        Escape(l);
        Check(!(bool)Field(l,"windowClosed"),"Home Escape closed launcher");
        State(l,new Dictionary<string,object>{{"installed",true},{"ready",true},{"spanish_installed",true},{"hd_textures_installed",true}});
        Check(Visible(l,"PlayButton")&&!Visible(l,"ImportButton")&&!Visible(l,"HomeExistingButton"),"Ready home shows multiple primary actions");
        Manage(l);
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","cancel");
        Task job=Run(l,"--verify");
        foreach(string name in new[]{"LaunchActions","ManagePanel","ManageButton","BackButton","ReleaseButton"})
            Check(!Visible(l,name),"Busy operation exposes "+name);
        Check(Visible(l,"CancelButton")&&Visible(l,"StatusText")&&Visible(l,"Progress"),"Busy operation hides status/progress/cancel");
        Escape(l);
        Check((bool)Field(l,"manageOpen")&&(bool)Field(l,"busy")&&!File.Exists((string)Field(l,"cancelFile")),"Escape canceled or navigated away from an active operation");
        Click(l,"CancelButton");Finish(job);Idle(l);
        Check(Visible(l,"ManagePanel")&&(bool)Field(l,"manageOpen"),"Cancellation did not restore Manage");
        Check(Element<TextBlock>(l,"StatusText").Text=="Canceled safely","Returning Manage hid cancellation outcome");
        State(l,new Dictionary<string,object>{{"installed",true},{"ready",false},{"update_available",true}});
        Check(Visible(l,"ManagePanel"),"Local update state forced Manage closed");
        Click(l,"BackButton");
        Check(Visible(l,"ImportButton")&&(string)Element<Button>(l,"ImportButton").Content=="UPDATE GAME","Stale install home lacks direct update");
        State(l,new Dictionary<string,object>{{"update_available",false}});
        Check(Visible(l,"ImportButton")&&Visible(l,"ManageButton"),"Broken installation lost recovery actions");
        Manage(l);
        Check(Visible(l,"RepairIsoButton")&&Visible(l,"VerifyButton"),"Broken installation cannot be repaired from Manage");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","success");
        Evidence["home_manage_navigation_busy_cancel_and_repair"]=true;
    }

    static void ReuseAndUpdate() {
        var l=new Launcher(true);
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","attach");
        Finish((Task)Call(l,"Run","--use-installation",@"E:\My Games\Darkwatch Español 🦇\GameData")); Idle(l);
        Check((bool)Field(l,"updateAvailable")&&(bool)Field(l,"installed")&&!(bool)Field(l,"ready"),"Attach lost update-required state");
        Check(((string)Field(l,"gameDirectory")).StartsWith(@"E:\Existing"),"Selected external game folder lost");
        Check((string)Element<Button>(l,"ImportButton").Content=="UPDATE GAME","Update did not become primary action");
        Check(Visible(l,"ImportButton"),"Outdated installation hides its home update action");
        Manage(l);
        Check(Element<Button>(l,"RepairIsoButton").IsEnabled&&Visible(l,"RepairIsoButton"),"Manage hides manual ISO repair");
        Click(l,"BackButton");
        Check(!Element<Button>(l,"PlayButton").IsEnabled,"Outdated installation became playable");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","update");
        Click(l,"ImportButton");
        Check((bool)Field(l,"busy"),"Primary update did not invoke backend");
        Check(!Element<Button>(l,"ExistingInstallButton").IsEnabled,"Busy update allowed switching installations");
        Pump(()=>!(bool)Field(l,"busy")); Idle(l);
        Check(!(bool)Field(l,"updateAvailable")&&(bool)Field(l,"ready"),"Successful update did not restore play");
        Check(Element<TextBlock>(l,"StatusText").Text=="Updated fixture only","Update did not run exact action");
        Check(Visible(l,"PlayButton")&&!Visible(l,"ImportButton"),"Successful update did not restore the simple Play home");
        State(l,new Dictionary<string,object>{{"ready",false},{"update_available",true},{"language","es"}});
        Check((string)Element<Button>(l,"ImportButton").Content=="ACTUALIZAR JUEGO","Spanish update action missing");
        Check((string)Element<Button>(l,"ExistingInstallButton").Content=="USAR INSTALACIÓN EXISTENTE","Spanish existing install action missing");
        Evidence["reuse_in_place_unicode_path_and_explicit_update"]=true;
    }

    static void ReleaseChecks() {
        string calls=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"release-check-calls.txt");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_RELEASE_CALLS",calls);
        Environment.SetEnvironmentVariable("DARKWATCH_UI_RELEASE_MODE","available");
        var l=new Launcher(true);
        State(l,new Dictionary<string,object>{{"installed",true},{"ready",true},{"message","Installed fixture state"},{"percent",81}});
        Check(!Visible(l,"ReleaseButton")&&!Visible(l,"CheckUpdatesButton"),"Home contains an idle update action");
        var check=(Task)Call(l,"CheckForUpdates");
        Check((bool)Field(l,"checkingRelease")&&!(bool)Field(l,"busy"),"Online check blocked installation controls");
        Check(Element<Button>(l,"PlayButton").IsEnabled&&Element<Button>(l,"ImportButton").IsEnabled,"Online check disabled Play or Import");
        Check(!Element<Button>(l,"ReleaseButton").IsEnabled,"In-flight check remains clickable");
        Finish((Task)Call(l,"CheckForUpdates"));
        Finish(check);
        Check(File.ReadAllLines(calls).Length==1,"Concurrent release checks were not deduplicated");
        Check(Element<TextBlock>(l,"StatusText").Text=="Installed fixture state"&&Element<ProgressBar>(l,"Progress").Value==81,"Online helper stole install status or progress");
        Check((bool)Field(l,"ready")&&Field(l,"cancelFile")==null,"Online helper mutated readiness or cancellation");
        Check((string)Field(l,"releaseStatus")=="available"&&(string)Element<Button>(l,"ReleaseButton").Content=="INSTALL UPDATE","Available release action missing");
        Check(Visible(l,"ReleaseButton")&&Visible(l,"ReleaseStatus"),"Available release is not discoverable from home");
        Check(Launcher.ValidReleaseUrl((string)Field(l,"releaseUrl"),"0.7"),"Valid official release URL rejected");
        foreach(string invalid in new[]{"http://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7",
            "https://github.com.evil.example/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7",
            "https://github.com/other/DarkwatchDarkerEdition/releases/tag/v0.7",
            "https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7?download=1",
            "https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7\n",
            "file:///C:/evil.exe","https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.8"})
            Check(!Launcher.ValidReleaseUrl(invalid,"0.7"),"Unsafe or mismatched release URL accepted");
        Check(!Launcher.ValidReleaseUrl("https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v０.７","０.７"),"Unicode version accepted");
        Manage(l);
        foreach(string mode in new[]{"unavailable","failure","malicious","current"}) {
            Environment.SetEnvironmentVariable("DARKWATCH_UI_RELEASE_MODE",mode);
            Check(Visible(l,"CheckUpdatesButton"),"Manual update check is hidden in Manage");
            Click(l,"CheckUpdatesButton");
            Pump(()=>!(bool)Field(l,"checkingRelease"));
            Check((string)Field(l,"releaseStatus")== (mode=="current"?"current":"unavailable"),"Bad release outcome handling: "+mode);
            Check(Field(l,"releaseUrl")==null&&Element<Button>(l,"CheckUpdatesButton").IsEnabled&&!Visible(l,"ReleaseButton"),"Failed check kept unsafe/stale action or disabled retry");
            Check(Element<TextBlock>(l,"StatusText").Text=="Installed fixture state"&&Element<Button>(l,"PlayButton").IsEnabled,"Failure blocked installed game");
            Check(Visible(l,"ManagePanel")&&(bool)Field(l,"manageOpen"),"Delayed update result changed the selected panel");
        }
        Environment.SetEnvironmentVariable("DARKWATCH_UI_RELEASE_MODE","unavailable");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","cancel");
        Task import=Run(l,"--import-iso");
        string token=(string)Field(l,"cancelFile");
        Check(!Element<Button>(l,"ReleaseButton").IsEnabled,"Installation allowed starting another update");
        var independentCheck=(Task)Call(l,"CheckForUpdates");
        Finish(independentCheck);
        Pump(()=>!(bool)Field(l,"checkingRelease"));
        Check((bool)Field(l,"busy")&&(string)Field(l,"cancelFile")==token&&!File.Exists(token),"Online check altered active import/cancel token");
        Click(l,"CancelButton"); Finish(import); Idle(l);
        State(l,new Dictionary<string,object>{{"language","es"}});
        Check(Element<TextBlock>(l,"ReleaseStatus").Text=="No se pudo comprobar"&&(string)Element<Button>(l,"CheckUpdatesButton").Content=="BUSCAR ACTUALIZACIONES","Release state did not relocalize");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","success");
        var startup=new Launcher(true);int before=File.ReadAllLines(calls).Length;
        var first=(Task)Call(startup,"Startup");var second=(Task)Call(startup,"Startup");Finish(first);Finish(second);
        Check(File.ReadAllLines(calls).Length==before+1,"Startup checked more than once");
        Check(!Visible(startup,"ReleaseStatus")&&!Visible(startup,"ReleaseButton"),"Background offline result clutters the home screen");
        var preparation=Launcher.Preparing(()=>{});before=File.ReadAllLines(calls).Length;
        Finish((Task)Call(preparation,"Startup"));Finish((Task)Call(preparation,"CheckForUpdates"));
        Check(File.ReadAllLines(calls).Length==before&&Element<Grid>(preparation,"ReleaseActions").Visibility==Visibility.Collapsed,"Direct preparation started release check");
        var closed=new Launcher(true);check=(Task)Call(closed,"CheckForUpdates");closed.Window.Close();Finish(check);
        Check(!(bool)Field(closed,"checkingRelease")&&!closed.Window.IsVisible,"Closing during background check failed");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_RELEASE_CALLS",null);
        Evidence["release_check_independent_retry_localized_safe_links"]=true;
        Evidence["release_check_startup_once_and_no_direct_play_check"]=true;
    }

    static void DownloadUpdates() {
        foreach(string mode in new[]{"download-failure","download-missing","cancel"}) {
            var l=new Launcher(true);
            State(l,new Dictionary<string,object>{{"installed",true},{"ready",true},{"hd_textures_installed",true},{"spanish_installed",true},{"language","es"},{"install_dir",@"E:\Existing\Active"}});
            Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE",mode);
            Task job=Run(l,"--download-update");
            Check((bool)Field(l,"busy")&&!Element<Button>(l,"PlayButton").IsEnabled&&!Element<Button>(l,"ReleaseButton").IsEnabled,"Download did not lock mutation actions");
            if(mode=="cancel")Click(l,"CancelButton");
            Finish(job);Idle(l);
            Check((bool)Field(l,"ready")&&(bool)Field(l,"installed")&&(bool)Field(l,"hdTexturesInstalled")&&(bool)Field(l,"spanishInstalled"),"Failed/cancelled download disabled prior installation");
            Check((string)Field(l,"language")=="es"&&(string)Field(l,"gameDirectory")==@"E:\Existing\Active","Failed download changed prior install settings");
            Check(!(bool)Field(l,"windowClosed"),"Failed download closed launcher");
        }
        var success=new Launcher(true);
        Environment.SetEnvironmentVariable("DARKWATCH_UI_RELEASE_MODE","available");
        Finish((Task)Call(success,"CheckForUpdates"));
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","download");
        Click(success,"ReleaseButton");
        Check((bool)Field(success,"busy"),"Release action did not start download");
        Pump(()=>!(bool)Field(success,"busy"));
        Check((bool)Field(success,"windowClosed"),"Prepared release did not close launcher for independent worker");
        Check(Field(success,"cancelFile")==null,"Prepared release retained private cancel token");

        string actions=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"complete-update-actions.txt");
        foreach(string mode in new[]{"startup-update","startup-fresh"}) {
            File.WriteAllText(actions,"");Environment.SetEnvironmentVariable("DARKWATCH_UI_ACTIONS",actions);
            Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE",mode);
            var l=new Launcher(true);typeof(Launcher).GetField("completeUpdate",Private).SetValue(l,true);
            Finish((Task)Call(l,"Startup"));
            string[] seen=File.ReadAllLines(actions);
            Check(seen.Contains("--status")&&seen.Contains("--check-updates"),"Restart skipped status/check");
            Check(seen.Contains("--update")== (mode=="startup-update"),"Restart updated absent installation or skipped pending data");
            Check(!seen.Contains("--play")&&!seen.Contains("--download-update")&&!seen.Contains("--import-iso"),"Restart unexpectedly launched or reimported game");
            if(mode=="startup-update")Check((bool)Field(l,"ready")&&!(bool)Field(l,"updateAvailable"),"Restart did not finish local data update");
        }
        Environment.SetEnvironmentVariable("DARKWATCH_UI_ACTIONS",null);
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","success");
        Evidence["explicit_download_cancel_restore_worker_handoff"]=true;
        Evidence["restart_completion_updates_existing_data_without_play"]=true;
    }

    static void DropInIso() {
        string root=AppDomain.CurrentDomain.BaseDirectory, assets=Path.Combine(root,"assets"), actions=Path.Combine(root,"drop-actions.txt");
        Directory.CreateDirectory(assets);
        string iso=Path.Combine(assets,"Darkwatch Español 🦇.XISO"), second=Path.Combine(assets,"another.iso");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_DROP_ISO",iso);
        Environment.SetEnvironmentVariable("DARKWATCH_UI_ACTIONS",actions);
        Environment.SetEnvironmentVariable("DARKWATCH_UI_RELEASE_MODE","unavailable");
        foreach(string mode in new[]{"drop-none","drop-one","drop-multiple","drop-installed","drop-unsupported","drop-status-failure"}) {
            File.WriteAllText(actions,"");File.Delete(iso);File.Delete(second);
            File.WriteAllText(Path.Combine(assets,"README.txt"),"instruction fixture");
            if(mode!="drop-none")File.WriteAllText(iso,"unchanged ISO fixture");
            if(mode=="drop-multiple")File.WriteAllText(second,"second fixture");
            Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE",mode);
            var l=new Launcher(true);var task=(Task)Call(l,"Startup");
            Check(!task.IsCompleted,"Startup blocked UI instead of awaiting its helper");
            Finish(task);Finish((Task)Call(l,"Startup"));
            string[] seen=File.ReadAllLines(actions);
            bool attempted=mode=="drop-one"||mode=="drop-unsupported";
            Check(seen.Count(x=>x=="--status")==1&&seen.Count(x=>x=="--use-iso")== (attempted?1:0),"Wrong or repeated automatic ISO action: "+mode);
            Check(!seen.Contains("--import-iso")&&!seen.Contains("--play"),"Auto-detection extracted the whole ISO or launched a game");
            if(File.Exists(iso))Check(File.ReadAllText(iso)=="unchanged ISO fixture","Auto-detection changed source ISO");
            if(mode=="drop-one")Check((bool)Field(l,"ready")&&!(bool)Field(l,"sourceOpen"),"Drop-in did not finish normally");
            if(mode=="drop-multiple"||mode=="drop-unsupported")Check((bool)Field(l,"sourceOpen"),"Ambiguous/unsupported image lost source chooser");
            if(mode=="drop-unsupported")Check(Element<TextBlock>(l,"StatusText").Text.Contains("Unsupported"),"Unsupported ISO error was hidden");
            Idle(l);
        }
        File.Delete(iso);File.Delete(second);
        Environment.SetEnvironmentVariable("DARKWATCH_UI_DROP_ISO",null);Environment.SetEnvironmentVariable("DARKWATCH_UI_ACTIONS",null);
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","success");
        Evidence["drop_in_iso_fresh_async_once_existing_ambiguous_unsupported_guards"]=true;
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
        Check(Launcher.SpanishPackFilter=="PS2 Darkwatch disc image (*.iso)|*.iso","Spanish picker accepts unexpected formats");
        var l=new Launcher(true);
        State(l,new Dictionary<string,object>{{"installed",true},{"ready",true},{"language","en"},{"spanish_installed",false}});
        Manage(l);
        Check(Visible(l,"LanguageChoice")&&Visible(l,"SpanishButton"),"Manage hides language controls");
        Check(Element<Button>(l,"SpanishButton").IsEnabled,"Ready game cannot install Spanish");
        Check(Element<ComboBox>(l,"LanguageChoice").IsEnabled&&!Element<ComboBoxItem>(l,"SpanishChoice").IsEnabled,"Missing pack must disable Spanish only");
        Element<ComboBox>(l,"LanguageChoice").SelectedIndex=1;
        Check(Element<ComboBox>(l,"LanguageChoice").SelectedIndex==0&&!(bool)Field(l,"busy"),"Missing pack selection reached backend");
        Check((string)Element<Button>(l,"SpanishButton").Content=="INSTALL SPANISH","Spanish install action missing");
        Check(((string)Element<Button>(l,"SpanishButton").ToolTip).Contains("PS2 Darkwatch ISO (SLES-53564)"),"Supported own-disc import is not explained");
        Check(Element<TextBlock>(l,"LanguageStatus").Text.Contains("requires your PS2 ISO"),"Missing import is not explained");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","spanish-iso");
        Finish((Task)Call(l,"Run","--install-spanish",@"C:\My Games\PS2 Español 🦇.iso")); Idle(l);
        Check(Element<ComboBoxItem>(l,"SpanishChoice").IsEnabled,"Installed Spanish still disabled");
        Check(Element<TextBlock>(l,"LanguageStatus").Text.Contains("Spanish installed"),"Installed translation is not explained");
        Environment.SetEnvironmentVariable("DARKWATCH_UI_FIXTURE_MODE","language-es");
        Element<ComboBox>(l,"LanguageChoice").SelectedIndex=1;
        Pump(()=>!(bool)Field(l,"busy")); Idle(l);
        Check((string)Field(l,"language")=="es","Imported Spanish could not be selected");
        Evidence["ps2_iso_required_for_spanish_and_unicode_arguments"]=true;
        State(l,new Dictionary<string,object>{{"language","es"},{"spanish_installed",true}});
        Check(!(bool)Field(l,"busy")&&Element<ComboBox>(l,"LanguageChoice").SelectedIndex==1,"Programmatic language refresh started an operation");
        Check((string)Element<Button>(l,"PlayButton").Content=="JUGAR","Spanish action missing");
        Check((bool)Field(l,"manageOpen")&&Visible(l,"ManagePanel"),"Language change left Manage");
        Check(((string)Element<Button>(l,"SpanishButton").Content).Contains("ESPAÑOL"),"Spanish accent lost");
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
        Check(!Visible(preparation,"LanguageActions"),"Preparation exposed language mutations");
        Check(!Visible(preparation,"SourceActions"),"Preparation exposed installation selection");
        foreach(string name in new[]{"LaunchActions","ManagePanel","ManageButton","BackButton","HomeExistingButton","CheckUpdatesButton"})
            Check(!Visible(preparation,name),"Direct preparation exposes "+name);
        preparation.UpdatePreparation(new Dictionary<string,object>{{"event","progress"},{"message","Preparing selectable characters..."},{"percent",80}});
        Check(Element<TextBlock>(preparation,"StateTitle").Text=="PREPARANDO EL JUEGO","Asset update is mislabeled as shaders");
        Evidence["language_selection_install_rollback_and_no_reentrancy"]=true;
    }

    static void Preview(string destination) {
        Directory.CreateDirectory(destination);
        foreach(string state in new[]{"fresh","source","spanish-source","ready","hd-installed","importing","shaders","spanish-ready","spanish-shaders","update","spanish-update","new-release","spanish-offline","manage","spanish-manage","fresh-manage"}) {
            var l=state.EndsWith("shaders")?Launcher.Preparing(()=>{}):new Launcher(true);string path=Path.Combine(destination,"launcher-"+state+".png");
            Call(l,"FitToWorkArea",new Rect(0,0,1920,1080));
            var root=(Visual)l.Window.Content;
            l.RenderPreview(path,state);
            Check(!l.Window.IsVisible,"Preview showed a desktop window");
            foreach(string name in new[]{"ImportButton","PlayButton","VerifyButton","FolderButton","TextureButton","SpanishButton","ExistingInstallButton","RepairIsoButton","CancelButton","ReleaseButton","ManageButton","BackButton","HomeExistingButton","CheckUpdatesButton","UseIsoButton","ExtractIsoButton","SourceBackButton"}) {
                var button=Element<Button>(l,name);
                if(!Visible(button)||button.RenderSize.Width==0)continue;
                var bounds=button.TransformToAncestor(root).TransformBounds(new Rect(new Point(),button.RenderSize));
                Check(bounds.Left>=0&&bounds.Top>=0&&bounds.Bottom<=720&&bounds.Right<=1060,"Clipped "+name+" in "+state);
            }
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

    static void ReleaseAndSmallDesktop(string release, string version) {
        var file=FileVersionInfo.GetVersionInfo(release);
        string assemblyVersion=String.Join(".",version.Split('.').Concat(Enumerable.Repeat("0",4-version.Split('.').Length)));
        Check(AssemblyName.GetAssemblyName(release).Version.ToString()==assemblyVersion,"Compiled launcher assembly version differs from package");
        Check(file.FileVersion==assemblyVersion&&file.ProductVersion==version,"Compiled launcher version labels differ from package");
        Evidence["release_version"]=version;
        var type=Assembly.LoadFile(release).GetType("DarkwatchDarkerEdition.Launcher");
        Check(type.GetMethod("RenderPreview")==null,"Release launcher exposes preview diagnostics");
        Check(type.GetConstructors().All(c=>c.GetParameters().Length==0),"Release launcher accepts testing mode");
        foreach(var area in new[]{new Rect(0,0,1280,680),new Rect(0,0,960,520),new Rect(0,0,800,560)}) {
            foreach(string state in new[]{"fresh","source","spanish-source","ready","manage","spanish-manage","fresh-manage","manage-error","update","broken"}) {
                var l=new Launcher(true);Call(l,"FitToWorkArea",area);
                if(!state.StartsWith("fresh"))State(l,new Dictionary<string,object>{
                    {"installed",true},{"ready",state!="update"&&state!="broken"},{"update_available",state=="update"},
                    {"hd_textures_installed",true},{"spanish_installed",true},{"language",state.StartsWith("spanish-")?"es":"en"}});
                if(state.EndsWith("manage")||state=="manage-error")Manage(l);
                if(state.EndsWith("source"))Call(l,"ShowSource",true);
                if(state=="manage-error")Call(l,"Error",new string('E',500));
                Check(l.Window.Width<=area.Width-24&&l.Window.Height<=area.Height-24,"Launcher exceeds desktop work area");
                var content=(FrameworkElement)l.Window.Content;
                content.Measure(new Size(l.Window.Width,l.Window.Height));
                content.Arrange(new Rect(0,0,l.Window.Width,l.Window.Height));content.UpdateLayout();
                var active=new List<Rect>();
                foreach(string name in new[]{"ImportButton","PlayButton","VerifyButton","FolderButton","TextureButton","SpanishButton","ExistingInstallButton","RepairIsoButton","ReleaseButton","CloseButton","ManageButton","BackButton","HomeExistingButton","CheckUpdatesButton","UseIsoButton","ExtractIsoButton","SourceBackButton"}) {
                    var button=Element<Button>(l,name);
                    if(!Visible(button))continue;
                    Check(button.RenderSize.Width>0&&button.RenderSize.Height>0,"Visible control has no layout: "+name);
                    var bounds=button.TransformToAncestor(content).TransformBounds(new Rect(new Point(0,0),button.RenderSize));
                    Check(bounds.Left>=0&&bounds.Top>=0&&bounds.Right<=l.Window.Width+1&&bounds.Bottom<=l.Window.Height+1,
                          "Clipped launcher button "+name+" in "+state+" on small/high-DPI desktop");
                    foreach(var previous in active) {
                        var intersection=Rect.Intersect(bounds,previous);
                        Check(intersection.IsEmpty||intersection.Width<1||intersection.Height<1,"Overlapping action: "+name+" in "+state);
                    }
                    active.Add(bounds);
                }
                var description=Element<TextBlock>(l,"StateDescription").TransformToAncestor(content).TransformBounds(new Rect(new Point(),Element<TextBlock>(l,"StateDescription").RenderSize));
                var status=Element<TextBlock>(l,"StatusText").TransformToAncestor(content).TransformBounds(new Rect(new Point(),Element<TextBlock>(l,"StatusText").RenderSize));
                Check(description.Bottom<=status.Top+1,"Status overlaps launcher description in "+state);
                foreach(var button in active) {
                    var intersection=Rect.Intersect(status,button);
                    Check(intersection.IsEmpty||intersection.Width<1||intersection.Height<1,"Status overlaps a management action in "+state);
                }
                Check(!l.Window.IsVisible,"Small desktop check showed a window");
            }
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
            Quote(); ResourcesAndState(); SourceSelection(); ProcessEvents(); Navigation(); ReuseAndUpdate(); ReleaseChecks(); DownloadUpdates(); DropInIso(); Cancellation(); Language(); Preview(args[0]); ReleaseAndSmallDesktop(args[1],args[2]);
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
            import ast
            tree = ast.parse((ROOT / "launcher/package.py").read_text(encoding="utf-8"))
            version = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets))
            result = subprocess.run([str(executable), str(evidence), str(production), version], capture_output=True, encoding="utf-8-sig", timeout=35)
            (evidence / "harness.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            report["source_sha256"] = {name: hashlib.sha256((ROOT / "launcher" / name).read_bytes()).hexdigest() for name in ["Launcher.cs", "SetupProcess.cs", "MainWindow.xaml", "assets/cover-darker-edition.png", "assets/insignia.png"]}
            (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            self.assertTrue(report["cancel_event_and_locked_token_recovery"])
            self.assertTrue(report["home_manage_navigation_busy_cancel_and_repair"])
            self.assertEqual(report["shown_windows"], 0)
            self.assertFalse(report["real_backend_or_game_started"])
            self.assertEqual(report["release_version"], version)
            self.assertTrue(report["release_preview_api_absent"])
            self.assertEqual(report["scaled_workareas_checked"], 3)


if __name__ == "__main__":
    unittest.main()
