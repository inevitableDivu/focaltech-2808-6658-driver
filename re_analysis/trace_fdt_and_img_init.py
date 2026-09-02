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

# Let's inspect fw9366_fdt_mode_init at 0x180004a70 to 0x180005d00
# Let's write a targeted disassembler to extract register writes and SRAM writes
code = get_code(0x180004a70, 0x180005d00 - 0x180004a70)
print("=== Register / SRAM interactions in fw9366_fdt_mode_init ===")

# Let's disassemble and find all calls to write_reg (0x18000a434), read_reg (0x18000a3d8), 
# sram_write (0x18000a650), etc.
prev_insns = []
for insn in cs.disasm(code, 0x180004a70):
    prev_insns.append(insn)
    if len(prev_insns) > 10:
        prev_insns.pop(0)
    
    if insn.mnemonic == 'call':
        target = insn.op_str
        if any(f in target for f in ["0x18000a434", "0x18000a3d8", "0x18000a624", "0x18000a47c", "0x18000a650", "0x18000a700", "0x18000a200"]):
            print(f"0x{insn.address:x}: CALL {target}")
            for p in prev_insns[-5:-1]:
                print(f"   0x{p.address:x}: {p.mnemonic:8s} {p.op_str}")

