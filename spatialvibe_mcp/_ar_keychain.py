"""Read only explicitly configured macOS Keychain credentials (43 base64url chars); never print them."""
import ctypes
import re
import sys


class KeychainError(RuntimeError):
    pass


def read_upload_token(service: str, account: str = "upload") -> str:
    if (sys.platform != "darwin" or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", service)
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,40}", account)):
        raise KeychainError("AR keychain credential is unavailable")
    security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
    interaction = security.SecKeychainSetUserInteractionAllowed
    interaction.argtypes = [ctypes.c_bool]
    interaction.restype = ctypes.c_int32
    find = security.SecKeychainFindGenericPassword
    find.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                     ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32),
                     ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    find.restype = ctypes.c_int32
    release = security.SecKeychainItemFreeContent
    release.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    release.restype = ctypes.c_int32
    # Noninteractive stdio server: do not trigger authentication/password prompts.
    if interaction(False) != 0:
        raise KeychainError("AR keychain credential is unavailable")
    encoded = service.encode("ascii")
    account = account.encode("ascii")
    length, data = ctypes.c_uint32(), ctypes.c_void_p()
    status = find(None, len(encoded), encoded, len(account), account,
                  ctypes.byref(length), ctypes.byref(data), None)
    try:
        if status != 0 or length.value != 43 or not data.value:
            raise KeychainError("AR keychain credential is unavailable")
        value = ctypes.string_at(data, length.value).decode("ascii")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
            raise KeychainError("AR keychain credential is invalid")
        return value
    except UnicodeError:
        raise KeychainError("AR keychain credential is invalid") from None
    finally:
        if data.value:
            release(None, data)
