import pefile
import capstone
import struct

pe = pefile.PE("ftWbioUmdfDriverV2.dll")
image_base = pe.OPTIONAL_HEADER.ImageBase

text_section = None
rdata_section = None
data_section = None

for s in pe.sections:
    name = s.Name.decode('utf-8', errors='ignore').strip('\x00')
    if name == '.text':
        text_section = s
    elif name == '.rdata':
        rdata_section = s
    elif name == '.data':
        data_section = s

print(f"ImageBase: 0x{image_base:x}")
print(f"Text section: VA=0x{text_section.VirtualAddress:x}, Size=0x{text_section.SizeOfRawData:x}")

interesting_strings = [
    "fw9366_init_chip",
    "fw9366_cfg_init",
    "fw9366_fdt_mode_init",
    "fw9366_img_mode_init",
    "fw9366_capture_image",
    "fw9366_rawdata_to_image",
    "fw9366_sram_write_bulk",
    "fw9366_sram_read_bulk_withecc",
    "fw9366_fifo_read",
    "Read chipid: 0x%x",
    "focaltech:fw9366",
]

str_addrs = {}
for sec in [rdata_section, data_section, text_section]:
    if not sec: continue
    sec_data = sec.get_data()
    for s in interesting_strings:
        b = s.encode('utf-8')
        pos = 0
        while True:
            idx = sec_data.find(b, pos)
            if idx == -1: break
            va = image_base + sec.VirtualAddress + idx
            str_addrs.setdefault(s, []).append(va)
            pos = idx + 1

for s, addrs in str_addrs.items():
    print(f"String '{s}' at: {[hex(a) for a in addrs]}")

text_data = text_section.get_data()
text_va = image_base + text_section.VirtualAddress

cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
cs.detail = True

refs = {}
for insn in cs.disasm(text_data, text_va):
    for op in insn.operands:
        if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
            mem_target = insn.address + insn.size + op.mem.disp
            for s, addrs in str_addrs.items():
                if mem_target in addrs:
                    refs.setdefault(s, []).append((insn.address, insn.mnemonic, insn.op_str))

print("\n--- Cross References in .text ---")
for s, hits in refs.items():
    print(f"[{s}] referenced from:")
    for h in hits:
        print(f"  0x{h[0]:x}: {h[1]} {h[2]}")

