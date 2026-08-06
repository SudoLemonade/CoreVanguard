import ctypes
from ctypes import wintypes
import psutil

# --- Windows C-Struct Definitions ---
SE_PRIVILEGE_ENABLED = 0x00000002
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SystemMemoryListInformation = 80
Command_EmptyStandbyList = 4

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD),
                ("HighPart", wintypes.LONG)]

class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID),
                ("Attributes", wintypes.DWORD)]

class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD),
                ("Privileges", LUID_AND_ATTRIBUTES * 1)]

def is_admin():
    """Checks if the script is running as Administrator."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def clear_standby_memory():
    """Elevates process token privileges and flushes the Standby RAM list."""
    if not is_admin():
        print("[DENIED] Administrator rights required.")
        print("Please restart VS Code or PowerShell as Administrator.")
        return False

    print("[INFO] Administrator rights confirmed. Preparing memory flush...")

   # Load required Windows API DLLs
    GetCurrentProcess = ctypes.windll.kernel32.GetCurrentProcess
    GetCurrentProcess.restype = wintypes.HANDLE  # <-- FIX: Tell Python this is a 64-bit handle

    OpenProcessToken = ctypes.windll.advapi32.OpenProcessToken
    OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    OpenProcessToken.restype = wintypes.BOOL

    LookupPrivilegeValue = ctypes.windll.advapi32.LookupPrivilegeValueW
    AdjustTokenPrivileges = ctypes.windll.advapi32.AdjustTokenPrivileges
    NtSetSystemInformation = ctypes.windll.ntdll.NtSetSystemInformation

    # 1. Open the process token
    token_handle = wintypes.HANDLE()
    if not OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token_handle)):
        print("[ERROR] Failed to open process token.")
        return False

    # 2. Look up the LUID for the required privilege
    luid = LUID()
    if not LookupPrivilegeValue(None, "SeProfileSingleProcessPrivilege", ctypes.byref(luid)):
        print("[ERROR] Failed to lookup security privilege.")
        return False

    # 3. Adjust the token to enable the privilege
    tp = TOKEN_PRIVILEGES()
    tp.PrivilegeCount = 1
    tp.Privileges[0].Luid = luid
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED

    if not AdjustTokenPrivileges(token_handle, False, ctypes.byref(tp), ctypes.sizeof(tp), None, None):
        print("[ERROR] Failed to adjust token privileges.")
        return False

    # 4. Execute the Standby List flush via ntdll
    print("[INFO] Security token elevated. Flushing Standby List...")
    command = ctypes.c_int(Command_EmptyStandbyList)
    status = NtSetSystemInformation(SystemMemoryListInformation, ctypes.byref(command), ctypes.sizeof(command))
    
    if status == 0:
        print("[SUCCESS] Standby RAM Cache successfully cleared!")
        return True
    else:
        print(f"[ERROR] NtSetSystemInformation failed with NTSTATUS: {status}")
        return False

if __name__ == "__main__":
    print("--- Standby RAM Cleaner Test ---")
    
    # Show memory before
    mem_before = psutil.virtual_memory()
    free_before_mb = mem_before.free / (1024 * 1024)
    print(f"Active RAM Load: {mem_before.percent}%")
    print(f"Completely Free RAM Before: {free_before_mb:.0f} MB")
    
    # Run the cleaner
    print("-" * 30)
    clear_standby_memory()
    print("-" * 30)
    
    # Show memory after
    mem_after = psutil.virtual_memory()
    free_after_mb = mem_after.free / (1024 * 1024)
    print(f"Active RAM Load: {mem_after.percent}%")
    print(f"Completely Free RAM After:  {free_after_mb:.0f} MB")
    print(f"RAM Freed: {(free_after_mb - free_before_mb):.0f} MB")