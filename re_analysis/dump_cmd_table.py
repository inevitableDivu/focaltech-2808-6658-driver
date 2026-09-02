import pefile

pe = pefile.PE("ftWbioUmdfDriverV2.dll")
image_base = pe.OPTIONAL_HEADER.ImageBase
text_sec = [s for s in pe.sections if s.Name.startswith(b'.text')][0]
text_data = text_sec.get_data()
text_va = image_base + text_sec.VirtualAddress

# Table at RIP + 0x2222d from 0x18000a7bc:
# RIP is 0x18000a7c3. 0x18000a7c3 + 0x2222d = 0x18002c9f0
table_va = 0x18002c9f0

# Find in rdata
rdata_sec = [s for s in pe.sections if s.Name.startswith(b'.rdata')][0]
rdata_data = rdata_sec.get_data()
rdata_va = image_base + rdata_sec.VirtualAddress

offset = table_va - rdata_va
table_data = rdata_data[offset:offset+60]

print("=== Command Table (0x18002c9f0) ===")
for i in range(15):
    entry = table_data[i*3 : (i+1)*3]
    print(f"Cmd {i:2d} (0x{i:02X}): [{', '.join(f'0x{b:02X}' for b in entry)}]")

