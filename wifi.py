import time
import network

try:
    import ubinascii as _binascii
except ImportError:
    import binascii as _binascii

from machine import unique_id


DEFAULTS = {
    "FORCE_AP_MODE": False,
    "STA_SSID": "YOUR_WIFI_NAME",
    "STA_PASSWORD": "YOUR_WIFI_PASSWORD",
    "STA_TIMEOUT_SECONDS": 15,
    "AP_SSID": "PICO86D6",
    "AP_PASSWORD": "CHANGE_THIS_PASSWORD",
    "AP_CHANNEL": 6,
    "NFC_ENABLED": True,
    "NFC_I2C_ID": 0,
    "NFC_SCL_PIN": 21,
    "NFC_SDA_PIN": 20,
    "NFC_SCAN_POST_URL": "",
}


def load_config():
    try:
        import wifi_config as cfg
    except ImportError:
        cfg = None

    config = {}
    for key, value in DEFAULTS.items():
        if cfg is None:
            config[key] = value
        else:
            config[key] = getattr(cfg, key, value)

    return config, cfg is not None


def get_device_uid_hex():
    return _binascii.hexlify(unique_id()).decode().upper()


def connect_sta(ssid, password, timeout_s):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        return wlan

    wlan.connect(ssid, password)

    for _ in range(timeout_s):
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        time.sleep(1)

    status = wlan.status()
    if status == 3:
        return wlan

    print("STA connect failed, status:", status)
    wlan.active(False)
    return None


def scan_networks():
    sta = network.WLAN(network.STA_IF)
    if not sta.active():
        sta.active(True)
        time.sleep(0.2)
    try:
        results = sta.scan()
    except OSError:
        return []

    entries = []
    seen = set()
    for item in results:
        ssid = item[0].decode("utf-8", "ignore").strip()
        rssi = item[3]
        if not ssid:
            continue
        if ssid in seen:
            continue
        seen.add(ssid)
        entries.append((ssid, rssi))

    entries.sort(key=lambda x: x[1], reverse=True)
    return entries


def save_wifi_config(ssid, password, config):
    content = """\"\"\"
Wi-Fi settings for Pico 2 W.
Auto-written by setup portal or NFC scan.
\"\"\"

# Set True to always boot as Access Point.
FORCE_AP_MODE = False

# Station mode (connect to existing router)
STA_SSID = {sta_ssid!r}
STA_PASSWORD = {sta_password!r}
STA_TIMEOUT_SECONDS = {timeout_s}

# Access Point mode (Pico creates its own Wi-Fi)
AP_SSID = {ap_ssid!r}
AP_PASSWORD = {ap_password!r}  # minimum 8 chars for WPA2
AP_CHANNEL = {ap_channel}

# NFC + cloud action settings
NFC_ENABLED = {nfc_enabled}
NFC_I2C_ID = {nfc_i2c_id}
NFC_SCL_PIN = {nfc_scl_pin}
NFC_SDA_PIN = {nfc_sda_pin}
NFC_SCAN_POST_URL = {nfc_scan_post_url!r}
""".format(
        sta_ssid=ssid,
        sta_password=password,
        timeout_s=config["STA_TIMEOUT_SECONDS"],
        ap_ssid=config["AP_SSID"],
        ap_password=config["AP_PASSWORD"],
        ap_channel=config["AP_CHANNEL"],
        nfc_enabled=config.get("NFC_ENABLED", True),
        nfc_i2c_id=config.get("NFC_I2C_ID", 0),
        nfc_scl_pin=config.get("NFC_SCL_PIN", 21),
        nfc_sda_pin=config.get("NFC_SDA_PIN", 20),
        nfc_scan_post_url=config.get("NFC_SCAN_POST_URL", ""),
    )
    with open("wifi_config.py", "w") as f:
        f.write(content)

