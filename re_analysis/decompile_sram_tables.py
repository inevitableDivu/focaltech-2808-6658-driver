import pefile
import capstone

pe = pefile.PE("ftWbioUmdfDriverV2.dll")
image_base = pe.OPTIONAL_HEADER.ImageBase
text_sec = [s for s in pe.sections if s.Name.startswith(b'.text')][0]
text_data = text_sec.get_data()
text_va = image_base + text_sec.VirtualAddress

cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)

def get_code(va, size):
    offset = va - text_va
    return text_data[offset:offset+size]

# Let's search for calls to fw9366_sram_write_bulk (0x18000a67c)
# to see where calibration or configuration tables are written to SRAM!
code = text_data
print("=== Calls to fw9366_sram_write_bulk (0x18000a67c / 0x18000a700) ===")
for insn in cs.disasm(code, text_va):
    if insn.mnemonic == 'call' and any(target in insn.op_str for target in ["0x18000a67c", "0x18000a650", "0x18000a700"]):
        print(f"0x{insn.address:x}: {insn.mnemonic:8s} {insn.op_str}")

