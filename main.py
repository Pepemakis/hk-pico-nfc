from machine import Pin, SPI, UART, ADC
from time import sleep_ms
import machine
import time
import sh1107
from uart import PN532_UART

from access_point import start_ap
from wifi import (
    load_config,
    connect_sta,
    scan_networks,
    save_wifi_config,
    get_device_uid_hex,
)
from local_server import start_http_server, serve_http_once
from cloud_client import post_json
from ota import perform_update, recover_if_needed


config, has_cfg = load_config()
print("Wi-Fi configuration:", "Using wifi_config.py" if has_cfg else "Using defaults (wifi_config.py not found)")
print("Boot config: STA_SSID={!r}, AP_SSID={!r}".format(config["STA_SSID"], config["AP_SSID"]))

# PN532 on I2C0:
# SDA -> GP4
# SCL -> GP5
# VCC -> 3V3
# GND -> GND
# slower I2C first

# UART0 for PN532
uart = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1))
pn532 = PN532_UART(uart, debug=False)

print("Searching PN532...")

ic, ver, rev, support = pn532.firmware_version
print("PN532 found")
print("IC:", hex(ic))
print("Firmware:", ver, ".", rev)
print("Support:", hex(support))

pn532.SAM_configuration()
print("Waiting for NFC tag...")


# ----------------------------
# Display setup (SPI1 on Pico / Pico 2W)
# ----------------------------
spi = SPI(
    1,
    baudrate=10_000_000,
    polarity=1,
    phase=1,
    sck=Pin(10),
    mosi=Pin(11),
    miso=Pin(12),  # not used by OLED, but OK
)

display = sh1107.SH1107_SPI(
    128,
    64,
    spi,
    dc=Pin(8),
    res=Pin(12),
    cs=Pin(9),
)

display.sleep(False)

SCAN_RESULT_MS = 3000
BATTERY_SAMPLE_MS = 5000
TOP_BAR_HEIGHT = 12

try:
    battery_adc = ADC(Pin(29))
except Exception:
    battery_adc = None

try:
    usb_power = Pin(24, Pin.IN)
except Exception:
    usb_power = None

battery_level = None
last_battery_sample_ms = time.ticks_ms()
wifi_icon_state = "offline"


def read_battery_level():
    if battery_adc is None:
        return None

    total = 0
    samples = 4
    for _ in range(samples):
        total += battery_adc.read_u16()
        sleep_ms(5)

    raw = total / samples
    voltage = (raw * 3.3 / 65535) * 3

    if voltage < 2.5 or voltage > 5.5:
        return None

    if voltage >= 4.15:
        return 4
    if voltage >= 3.95:
        return 3
    if voltage >= 3.7:
        return 2
    if voltage >= 3.3:
        return 1
    return 0


def usb_power_present():
    if usb_power is None:
        return False
    try:
        return usb_power.value() == 1
    except Exception:
        return False


def draw_wifi_icon(x, y, state):
    if state == "sta":
        display.pixel(x + 3, y + 1, 1)
        display.hline(x + 2, y + 3, 3, 1)
        display.hline(x + 1, y + 5, 5, 1)
        display.hline(x, y + 7, 7, 1)
        return

    if state == "ap":
        display.vline(x + 3, y, 8, 1)
        display.hline(x + 1, y + 2, 5, 1)
        display.hline(x, y + 4, 7, 1)
        display.hline(x + 2, y + 6, 3, 1)
        return

    display.hline(x, y + 6, 7, 1)
    display.pixel(x + 3, y + 3, 1)
    display.line(x, y, x + 6, y + 6, 1)


def draw_battery_icon(x, y, level):
    display.rect(x, y + 1, 12, 7, 1)
    display.fill_rect(x + 12, y + 3, 2, 3, 1)

    if level is None:
        display.line(x + 2, y + 6, x + 9, y + 2, 1)
        return

    fill_widths = (2, 4, 6, 8, 10)
    width = fill_widths[max(0, min(level, 4))]
    display.fill_rect(x + 1, y + 2, width, 5, 1)


def draw_usb_power_icon(x, y, present):
    if not present:
        return

    display.line(x + 3, y, x + 1, y + 4, 1)
    display.hline(x + 1, y + 4, 3, 1)
    display.line(x + 3, y + 4, x + 2, y + 8, 1)
    display.line(x + 2, y + 8, x + 5, y + 3, 1)
    display.hline(x + 3, y + 3, 3, 1)


def draw_top_bar():
    display.fill_rect(0, 0, 128, TOP_BAR_HEIGHT, 0)
    draw_wifi_icon(92, 1, wifi_icon_state)
    draw_usb_power_icon(104, 1, usb_power_present())
    draw_battery_icon(114, 1, battery_level)
    display.hline(0, TOP_BAR_HEIGHT, 128, 1)


def refresh_top_bar():
    draw_top_bar()
    display.show()


def update_battery_level(force=False):
    global battery_level, last_battery_sample_ms

    now = time.ticks_ms()
    if not force and time.ticks_diff(now, last_battery_sample_ms) < BATTERY_SAMPLE_MS:
        return

    last_battery_sample_ms = now
    new_level = read_battery_level()
    if force:
        battery_level = new_level
        return
    if new_level != battery_level:
        battery_level = new_level
        refresh_top_bar()


update_battery_level(force=True)


def show_status(mode, line2, line3):
    display.fill(0)
    draw_top_bar()
    display.text(mode, 0, 18, 1)
    display.text(line2, 0, 30, 1)
    display.text(line3, 0, 42, 1)
    display.show()


def show_progress_screen(mode, line2, line3, progress_width):
    show_status(mode, line2, line3)
    display.rect(0, 54, 128, 10, 1)
    if progress_width > 0:
        display.fill_rect(2, 56, min(progress_width, 124), 6, 1)
    display.show()


def show_ota_progress(stage, label, index, total):
    if stage == "prepare":
        show_status("OTA CHECK", "Update found", label[:16])
        return

    title = "OTA DL" if stage == "download" else "OTA APPLY"
    step_line = "{}/{}".format(index, total) if total else ""
    show_status(title, label[:16], step_line)


def run_ota_update():
    manifest_url = config.get("OTA_MANIFEST_URL", "").strip()
    if not config.get("OTA_ENABLED") or not config.get("OTA_CHECK_ON_BOOT", True):
        return
    if not manifest_url:
        return

    try:
        updated, result = perform_update(manifest_url, progress_cb=show_ota_progress)
    except Exception as exc:
        print("OTA failed:", exc)
        show_status("OTA FAIL", "Update error", str(exc)[:16])
        time.sleep(2.0)
        return

    if updated:
        print("OTA installed:", result)
        show_status("OTA OK", "Installed", "Rebooting...")
        time.sleep(1.5)
        machine.reset()

    print("OTA:", result)


# ----------------------------
# Boot networking logic
# ----------------------------
sta = None
ap = None
server = None
ap_ip = ""
last_uid = None
device_id = get_device_uid_hex()
scan_feedback_until = 0
scan_feedback_uid = None

recovery_state = recover_if_needed()
if recovery_state:
    show_status("OTA WARN", "Recovered", recovery_state.get("state", "")[:16])
    time.sleep(1.5)


def format_uid(uid_bytes):
    return ":".join("{:02X}".format(b) for b in uid_bytes)


def send_nfc_event(nfc_uid, flag):
    url = config.get("NFC_SCAN_POST_URL", "").strip()
    if not url:
        return False

    payload = {
        "device_id": device_id,
        "nfc_uid": nfc_uid,
        "flag": flag,
    }

    try:
        status_code, status_line = post_json(url, payload)
        print("Webhook POST:", status_code, status_line)
        return 200 <= status_code < 300
    except Exception as exc:
        print("Webhook POST failed:", exc)
        return False


if not config["FORCE_AP_MODE"] and config["STA_SSID"] != "YOUR_WIFI_NAME":
    wifi_icon_state = "offline"
    show_status("Wi-Fi: STA", "Connecting...", config["STA_SSID"][:16])
    sta = connect_sta(config["STA_SSID"], config["STA_PASSWORD"], config["STA_TIMEOUT_SECONDS"])

if sta and sta.isconnected():
    wifi_icon_state = "sta"
    ip = sta.ifconfig()[0]
    print("Connected to Wi-Fi")
    print("IP:", ip)
    show_status("Wi-Fi: STA", "Connected", ip)
    run_ota_update()
else:
    wifi_icon_state = "ap"
    ap = start_ap(config["AP_SSID"], config["AP_PASSWORD"], config["AP_CHANNEL"])
    ap_ip = ap.ifconfig()[0]
    print("AP mode enabled")
    print("SSID:", config["AP_SSID"])
    print("AP IP:", ap_ip)
    show_status("Wi-Fi: AP", config["AP_SSID"][:16], ap_ip)
    server = start_http_server()
    print("Open in browser: http://{}/".format(ap_ip))


# ----------------------------
# Keep-alive animation
# ----------------------------
x = 0
while True:
    now = time.ticks_ms()
    update_battery_level()

    if server:
        should_reboot = serve_http_once(
            server,
            ap_ip,
            config["AP_SSID"],
            scan_networks,
            lambda ssid, password: save_wifi_config(ssid, password, config),
        )
        if should_reboot:
            show_status("Wi-Fi: SETUP", "Saved config", "Rebooting...")
            time.sleep(1.0)
            try:
                server.close()
            except OSError:
                pass
            machine.reset()

    if scan_feedback_uid is not None:
        remaining = time.ticks_diff(scan_feedback_until, now)
        if remaining > 0:
            elapsed = SCAN_RESULT_MS - remaining
            progress = int((elapsed * 124) / SCAN_RESULT_MS)
            show_progress_screen("SCAN OK", "HTTP sent", scan_feedback_uid[:16], progress)
            time.sleep(0.08)
            continue
        scan_feedback_uid = None
        show_status("NFC READY", "Waiting tag...", "")

    uid = pn532.read_passive_target(timeout=500)
    if uid is not None:
        uid_hex = format_uid(uid)
        if uid_hex != last_uid:
            print("UID:", uid_hex)
            if send_nfc_event(uid_hex, 1):
                scan_feedback_uid = uid_hex
                scan_feedback_until = time.ticks_add(time.ticks_ms(), SCAN_RESULT_MS)
                show_progress_screen("SCAN OK", "HTTP sent", uid_hex[:16], 0)
            else:
                show_status("SCAN FAIL", "HTTP error", uid_hex[:16])
            last_uid = uid_hex
        sleep_ms(500)
    else:
        if last_uid is not None and scan_feedback_uid is None:
            send_nfc_event(last_uid, 0)
        last_uid = None
        display.fill_rect(0, 54, 128, 10, 0)
        display.fill_rect(x, 56, 10, 6, 1)
        display.show()
        x = (x + 4) % (128 - 10)
        time.sleep(0.08)
    
