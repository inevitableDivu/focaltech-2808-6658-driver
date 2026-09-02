import pefile
import capstone

pe = pefile.PE("ftWbioUmdfDriverV2.dll")
image_base = pe.OPTIONAL_HEADER.ImageBase
text_sec = [s for s in pe.sections if s.Name.startswith(b'.text')][0]
text_data = text_sec.get_data()
text_va = image_base + text_sec.VirtualAddress

rdata_sec = [s for s in pe.sections if s.Name.startswith(b'.rdata')][0]
rdata_data = rdata_sec.get_data()
rdata_va = image_base + rdata_sec.VirtualAddress

cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)

def get_code(va, size):
    offset = va - text_va
    return text_data[offset:offset+size]

# Let's disassemble the whole fw9366_img_mode_init function (0x1800085e0 to 0x180008c50)
code = get_code(0x1800085e0, 0x180008c50 - 0x1800085e0)
print("=== fw9366_img_mode_init Assembly ===")
for insn in cs.disasm(code, 0x1800085e0):
    # Print calls and reg writes
    if insn.mnemonic in ['call', 'mov', 'movzx', 'lea', 'jmp']:
        print(f"0x{insn.address:x}: {insn.mnemonic:8s} {insn.op_str}")

