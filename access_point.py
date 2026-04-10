import time
import network


def start_ap(ssid, password, channel):
    ap = network.WLAN(network.AP_IF)
    ap.active(False)
    time.sleep(0.2)
    ap.active(True)
    ap.config(essid=ssid, password=password, channel=channel)
    return ap

