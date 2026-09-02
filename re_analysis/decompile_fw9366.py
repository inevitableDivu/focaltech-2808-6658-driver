import pefile
import capstone

pe = pefile.PE("ftWbioUmdfDriverV2.dll")
image_base = pe.OPTIONAL_HEADER.ImageBase
text_sec = [s for s in pe.sections if s.Name.startswith(b'.text')][0]
text_data = text_sec.get_data()
text_va = image_base + text_sec.VirtualAddress

cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
cs.detail = True

def get_code(va, size):
    offset = va - text_va
    return text_data[offset:offset+size]

def disasm_func(va, max_insns=60):
    code = get_code(va, max_insns * 15)
    print(f"\n=== Function at 0x{va:x} ===")
    count = 0
    for insn in cs.disasm(code, va):
        print(f"0x{insn.address:x}: {insn.mnemonic:8s} {insn.op_str}")
        count += 1
        if count >= max_insns:
            break
        if insn.mnemonic in ['ret'] and count > 10:
            break

# Functions around xrefs:
# fw9366_fifo_read: 0x18000a200
# fw9366_sram_read_bulk_withecc: 0x18000a500
# fw9366_sram_write_bulk: 0x18000a700
# fw9366_init_chip: 0x180001800

disasm_func(0x18000a200, 50)
disasm_func(0x18000a550, 60)
disasm_func(0x18000a700, 60)

