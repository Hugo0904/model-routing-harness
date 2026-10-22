"""Optional native test fixture builder for TinyCC 0.9.27 x64; no downloads.

TinyCC writes relocation tables for DLL output. Keep those relocations and use
the exported _start as the EXE entry, with ASLR and NX enabled. No compiler/CRT
code is linked into this kernel32-only test payload.
"""
import argparse
from pathlib import Path
import struct
import subprocess
import tempfile


def build(compiler, output):
    output=Path(output).absolute()
    with tempfile.TemporaryDirectory(prefix='lpac-build-',dir=output.parent) as directory:
        dll=Path(directory)/'payload.dll'
        subprocess.run([str(compiler),'-nostdlib','-shared','-Wl,-export-all-symbols','-o',str(dll),
                        str(Path(__file__).with_name('lpac_payload.c')),'-lkernel32'],check=True,timeout=20)
        data=bytearray(dll.read_bytes())
    u16=lambda at:struct.unpack_from('<H',data,at)[0]
    u32=lambda at:struct.unpack_from('<I',data,at)[0]
    pe=u32(0x3c);opt=pe+24
    if u16(opt)!=0x20b:raise ValueError('x64_PE_required')
    sections=[]
    for i in range(u16(pe+6)):
        at=opt+u16(pe+20)+40*i
        sections.append((u32(at+12),max(u32(at+8),u32(at+16)),u32(at+20)))
    def offset(rva):return next(raw+rva-va for va,size,raw in sections if va<=rva<va+size)
    exports=offset(u32(opt+112))
    functions=offset(u32(exports+28));names=offset(u32(exports+32));ordinals=offset(u32(exports+36))
    entry=None
    for i in range(u32(exports+24)):
        at=offset(u32(names+4*i));end=data.index(0,at)
        if data[at:end]==b'_start':entry=u32(functions+4*u16(ordinals+2*i))
    if entry is None or not u32(opt+112+5*8+4):raise ValueError('entry_and_relocations_required')
    struct.pack_into('<I',data,opt+16,entry)
    struct.pack_into('<H',data,pe+22,u16(pe+22)&~0x2001)  # EXE, relocations retained
    struct.pack_into('<H',data,opt+68,3)  # console subsystem
    struct.pack_into('<H',data,opt+70,u16(opt+70)|0x140)  # DYNAMIC_BASE | NX_COMPAT
    output.write_bytes(data)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    build(args.cc,args.output)
