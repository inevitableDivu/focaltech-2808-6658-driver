import pefile

pe = pefile.PE("ftWbioUmdfDriverV2.dll")
for entry in pe.DIRECTORY_ENTRY_IMPORT:
    dll_name = entry.dll.decode('utf-8')
    print(f"DLL: {dll_name}")
    for imp in entry.imports:
        name = imp.name.decode('utf-8') if imp.name else f"ord({imp.ordinal})"
        if any(k in name.lower() for k in ["usb", "pipe", "device", "io", "read", "write", "transfer"]):
            print(f"  0x{imp.address:x}: {name}")

