"""Compile actual shader output and compare the portable infinity syntax to native DXBC.

No GPU or game is launched. Wine acceptance is recorded separately in private
analysis; native bytecode equality alone does not establish Proton rendering.
"""
import ctypes as c
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / 'third_party/XboxXBERecomp/runtime'


def original_syntax(source):
    assert source.count('asfloat(0x7f800000u)') == 1
    assert source.count('asfloat(0xff800000u)') == 2
    assert '#INF' not in source
    return source.replace('asfloat(0x7f800000u)', '1.#INF').replace('asfloat(0xff800000u)', '-1.#INF')


def helper_cases():
    source = (SDK / 'gpu/shaders.cpp').read_text()
    helpers = source[source.index('float4 ilu_rsq('):source.index('// power clamped to 128')]
    dynamic = ' { float4 a=ilu_rsq(v.x), b=ilu_log(v.y); return float4(a.x,b.x,b.z,a.z); }'
    bodies = {
        'dynamic-vs': ('vs_5_0', 'float4 main(float4 v:POSITION):SV_Position' + dynamic),
        'dynamic-ps': ('ps_5_0', 'float4 main(float4 v:TEXCOORD):SV_Target' + dynamic),
        'zero-cs': ('cs_5_0', '''RWStructuredBuffer<uint4> output:register(u0);
            [numthreads(1,1,1)] void main(uint3 id:SV_DispatchThreadID) {
                output[0]=asuint(ilu_rsq(0)); output[1]=asuint(ilu_log(0));
                output[2]=asuint(ilu_rsq(asfloat(0x80000000u)));
                output[3]=asuint(ilu_log(asfloat(0x80000000u))); }'''),
        'finite-cs': ('cs_5_0', '''RWStructuredBuffer<float4> output:register(u0);
            [numthreads(1,1,1)] void main(uint3 id:SV_DispatchThreadID) {
                output[0]=ilu_rsq(4); output[1]=ilu_rsq(-4);
                output[2]=ilu_log(2); output[3]=ilu_log(-2); }'''),
    }
    return {name: (profile, helpers + body) for name, (profile, body) in bodies.items()}




class NativeCompiler:
    def __init__(self):
        if not hasattr(c, 'WinDLL'):
            raise unittest.SkipTest('Windows D3D compiler required')
        self.library = c.WinDLL('d3dcompiler_47.dll')
        self.compile_shader = self.library.D3DCompile
        self.compile_shader.argtypes = [c.c_void_p, c.c_size_t, c.c_char_p, c.c_void_p, c.c_void_p,
                                        c.c_char_p, c.c_char_p, c.c_uint, c.c_uint,
                                        c.POINTER(c.c_void_p), c.POINTER(c.c_void_p)]
        self.compile_shader.restype = c.c_long

    @staticmethod
    def read_blob(blob):
        if not blob:
            return b''
        table = c.cast(blob, c.POINTER(c.POINTER(c.c_void_p))).contents
        try:
            pointer = c.WINFUNCTYPE(c.c_void_p, c.c_void_p)(table[3])(blob)
            size = c.WINFUNCTYPE(c.c_size_t, c.c_void_p)(table[4])(blob)
            return c.string_at(pointer, size)
        finally:
            c.WINFUNCTYPE(c.c_ulong, c.c_void_p)(table[2])(blob)

    def compile(self, source, profile):
        data = source.encode('ascii')
        code, errors = c.c_void_p(), c.c_void_p()
        # Optimization level 1 is zero, matching D3D12Backend::Compile.
        status = self.compile_shader(data, len(data), None, None, None, b'main', profile.encode(),
                                     0, 0, c.byref(code), c.byref(errors))
        message, bytecode = self.read_blob(errors), self.read_blob(code)
        assert status >= 0 and bytecode.startswith(b'DXBC'), message.decode('utf8', 'replace')
        return bytecode


class ShaderPortabilityTests(unittest.TestCase):
    def test_zero_branches_keep_exact_signed_infinity_bits(self):
        source = (SDK / 'gpu/shaders.cpp').read_text()
        original = original_syntax(source)
        self.assertEqual(sum(a != b for a, b in zip(source.splitlines(), original.splitlines(), strict=True)), 2)
        self.assertIn('v == 0 ? (asfloat(0x7f800000u)).xxxx', source)
        self.assertIn('mag == 0 ? float4(asfloat(0xff800000u), 1, asfloat(0xff800000u), 1)', source)
        self.assertEqual(struct.unpack('<f', struct.pack('<I', 0x7f800000))[0], float('inf'))
        self.assertEqual(struct.unpack('<f', struct.pack('<I', 0xff800000))[0], float('-inf'))

    def test_native_helper_bytecode_is_identical(self):
        compiler = NativeCompiler()
        for name, (profile, source) in helper_cases().items():
            with self.subTest(name=name):
                self.assertEqual(compiler.compile(original_syntax(source), profile), compiler.compile(source, profile))



if __name__ == '__main__':
    unittest.main()
