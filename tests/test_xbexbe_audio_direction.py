"""Native direction payloads through real HLE creation, sends and PCM output.

The original degree/sign convention and FullHRTF coefficient selection have a
separate private original-body witness. This tests discrete-speaker balance,
not Xbox filter/delay equivalence or a physical listening device.
"""
from pathlib import Path
import tempfile
import unittest

from test_xbexbe_audio_output import ROOT, SDK, SOURCE as ROUTING_SOURCE, compile_and_run


SOURCE = ROUTING_SOURCE[:ROUTING_SOURCE.index('int main() {')]
SOURCE = SOURCE.replace('Child(bool stream,unsigned channels=1)',
                        'Child(bool stream,unsigned channels=1,unsigned flags=0x400000)')
SOURCE = SOURCE.replace('W32(0x200,0x400000);', 'W32(0x200,flags);')
SOURCE = SOURCE.replace('W32(0x204,0x400000);', 'W32(0x204,flags);')
SOURCE += r'''
static X86Func* Sends(bool stream) { return stream ? GUEST(CDirectSoundStream_SetMixBins) : GUEST(IDirectSoundBuffer_SetMixBins); }
static X86Func* Use(bool stream) { return stream ? GUEST(IDirectSoundStream_Use3DVoiceData) : GUEST(IDirectSoundBuffer_Use3DVoiceData); }
static void Direction(uint32_t obj,bool stream,float azimuth,float elevation=0) {
    W32(0x800,0x40); W32(0x828,std::bit_cast<uint32_t>(azimuth)); W32(0x82C,std::bit_cast<uint32_t>(elevation));
    CHECK(Call(Data(stream),{obj,0x800})==0);
}
static void Same(const std::array<float,6>& a,const std::array<float,6>& b) {
    for(unsigned i=0;i<6;++i) Near(a[i],b[i]);
}
static void Mirror(const std::array<float,6>& a,const std::array<float,6>& b) {
    Near(a[0],b[1]); Near(a[1],b[0]); Near(a[4],b[5]); Near(a[5],b[4]);
    Near(a[2],b[2]); Near(a[3],b[3]);
}
static void Directional(bool stream,bool routed,bool surround) {
    ++case_id; audio::SetSurroundEnabled(surround);
    const auto parent=routed ? Parent() : 0;
    const auto child=Child(stream,1,routed ? 0x400000 : 0x400010);
    const auto spatial=routed ? parent : child; const bool spatial_stream=routed ? false : stream;
    if(routed) { Attach(child,stream,parent); Spatial(child,stream,0x33,0,0,0,0,0); }
    else CHECK(Call(Sends(stream),{child,Bins({{6,0},{8,0},{7,0},{9,0}})})==0);
    Spatial(spatial,spatial_stream,0x1F,0,0,0,-600,-10000);
    const auto baseline=Frame(); CHECK(baseline[0]>0 && baseline[0]==baseline[1]);
    if(surround) CHECK(baseline[4]>0 && baseline[4]==baseline[5]);
    Direction(spatial,spatial_stream,90); const auto right=Frame();
    Near(right[0],0); Near(right[4],0); Near(right[1],baseline[1]); Near(right[5],baseline[5]);
    Direction(spatial,spatial_stream,-90); const auto left=Frame(); Mirror(left,right);
    // Direction-only updates affect the next block, without new volume data or source restart.
    if(!stream) BufferPosition(child,6);
    Direction(spatial,spatial_stream,450); Same(Frame(),right);
    Direction(spatial,spatial_stream,-450); Same(Frame(),left);
    for(float az:{0.f,45.f,90.f,135.f,180.f}) {
        Direction(spatial,spatial_stream,az); const auto positive=Frame();
        Direction(spatial,spatial_stream,-az); Mirror(positive,Frame());
        for(unsigned s=0;s<6;++s) CHECK(positive[s]>=0 && positive[s]<=baseline[s]+.000003f);
    }
    Direction(spatial,spatial_stream,179.99f); const auto wrap=Frame();
    Direction(spatial,spatial_stream,-180.01f); Same(wrap,Frame());
    Direction(spatial,spatial_stream,90,90); Same(Frame(),baseline);
    Direction(spatial,spatial_stream,-90,-90); Same(Frame(),baseline);
    Direction(spatial,spatial_stream,90,60); const auto raised=Frame();
    CHECK(raised[0]>0 && raised[0]<baseline[0]); Near(raised[1],baseline[1]);
    for(auto angles:{std::pair{NAN,0.f},std::pair{INFINITY,0.f},std::pair{0.f,NAN},std::pair{0.f,INFINITY},std::pair{90.f,91.f}}) {
        Direction(spatial,spatial_stream,angles.first,angles.second); Same(Frame(),baseline);
    }
    // A full turn is continuous, bounded, and mirrors the rear pair without flipping it.
    Direction(spatial,spatial_stream,-180); auto previous=Frame();
    for(int az=-175;az<=180;az+=5) {
        Direction(spatial,spatial_stream,float(az)); const auto current=Frame();
        for(unsigned s=0;s<6;++s) {
            CHECK(current[s]>=0 && current[s]<=baseline[s]+.000003f);
            CHECK(std::abs(current[s]-previous[s])<=baseline[s]*.09f+.000003f);
        }
        previous=current;
    }
    Direction(spatial,spatial_stream,90);
    CHECK(Call(Use(spatial_stream),{spatial,0})==0); Same(Frame(),baseline);
    CHECK(Call(Use(spatial_stream),{spatial,1})==0); Same(Frame(),right);
    // Each original gain stage remains independent of balance.
    Spatial(spatial,spatial_stream,0x1F,0,0,-600,0,-10000);
    Direction(spatial,spatial_stream,135); const auto rear=Frame();
    CHECK(rear[1]>rear[0]); if(surround) CHECK(rear[5]>rear[1] && rear[5]>rear[4]);
    if(routed) {
        // Children use the parent's current direction; child payload cannot pan it twice.
        Direction(child,stream,-90); Same(Frame(),rear);
        const auto replacement=Parent(); Spatial(replacement,false,0x1F,0,0,0,-600,-10000);
        Direction(replacement,false,-90); Attach(child,stream,replacement); Same(Frame(),left);
        CHECK(Call(Release(false),{parent})==0);
        CHECK(Call(Release(false),{replacement})==1); Same(Frame(),left);
    }
    CHECK(Call(Release(stream),{child})==0); CHECK(allocations.empty());
}
static void ExplicitAndNonspatial(bool stream) {
    ++case_id; audio::SetSurroundEnabled(true);
    auto child=Child(stream,1,0x400010);
    CHECK(Call(Sends(stream),{child,Bins({{0,0},{1,0},{2,0},{3,0},{4,0},{5,0}})})==0);
    Spatial(child,stream,0x1F,0,0,0,0,0); const auto baseline=Frame();
    Direction(child,stream,90); Same(Frame(),baseline);
    Direction(child,stream,-90); Same(Frame(),baseline);
    // An explicit left send must survive a muted spatial left send to the same speaker.
    CHECK(Call(Sends(stream),{child,Bins({{0,-600},{6,0},{7,0},{2,0},{3,0}})})==0);
    Direction(child,stream,90); const auto mixed=Frame();
    Near(mixed[0],baseline[0]*Gain(600)); Near(mixed[1],baseline[1]);
    Near(mixed[2],baseline[2]); Near(mixed[3],baseline[3]);
    CHECK(Call(Release(stream),{child})==0);
    child=Child(stream); CHECK(Call(Sends(stream),{child,Bins({{6,0},{7,0},{8,0},{9,0}})})==0);
    Spatial(child,stream,0x1F,0,0,0,0,0); const auto nonspatial=Frame();
    Direction(child,stream,90); Same(Frame(),nonspatial);
    CHECK(Call(Release(stream),{child})==0); CHECK(allocations.empty());
}
static void DisabledMode() {
    ++case_id; auto child=Child(false,1,0x400010);
    CHECK(Call(Sends(false),{child,Bins({{6,0},{7,0},{8,0},{9,0}})})==0);
    Spatial(child,false,0x1F,0,0,0,0,0); const auto balanced=Frame();
    Direction(child,false,90); const auto right=Frame(); CHECK(right[0]==0 && right[1]>0);
    std::memset(memory+0xB00,0,0x40); W32(0xB3C,2);
    CHECK(Call(GUEST(IDirectSoundBuffer_SetAllParameters),{child,0xB00,0})==0); Same(Frame(),balanced);
    W32(0xB3C,0); CHECK(Call(GUEST(IDirectSoundBuffer_SetAllParameters),{child,0xB00,0})==0); Same(Frame(),right);
    CHECK(Call(Release(false),{child})==0); CHECK(allocations.empty());
}
int main() {
    audio::SetOutputChannels(6);
    for(bool stream:{false,true}) for(bool routed:{false,true}) for(bool surround:{false,true})
        Directional(stream,routed,surround);
    ExplicitAndNonspatial(false); ExplicitAndNonspatial(true); DisabledMode();
    std::printf("%u direction/PCM scenarios passed: full turn, mirror, bounds, stereo, parent, explicit sends and fallback\n",case_id);
}
'''


class DirectionTests(unittest.TestCase):
    def test_actual_pcm_direction_and_routes(self):
        with tempfile.TemporaryDirectory(prefix='xbexbe-direction-', dir=ROOT / 'build') as temp:
            result = compile_and_run(Path(temp), SOURCE, release=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ignored_direction_negative_control(self):
        mixer = (SDK / 'xdk/dsound.cpp').read_text()
        line = 'gain *= v.direction_balance[bin & 1];'
        self.assertEqual(mixer.count(line), 1)
        with tempfile.TemporaryDirectory(prefix='xbexbe-direction-negative-', dir=ROOT / 'build') as temp:
            result = compile_and_run(Path(temp), SOURCE, mixer.replace(line, 'gain *= 1.0f;'), release=True)
            self.assertEqual(result.returncode, 90, result.stdout + result.stderr)
            self.assertIn('PCM got ', result.stderr)


if __name__ == '__main__':
    unittest.main()
