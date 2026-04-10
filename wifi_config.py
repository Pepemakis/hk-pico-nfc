"""
Wi-Fi settings for Pico 2 W.
Auto-written by setup portal.
"""

# Set True to always boot as Access Point.
FORCE_AP_MODE = False

# Station mode (connect to existing router)
STA_SSID = 'M&A Home'
STA_PASSWORD = 'hhttTt5_$8277hHj'
STA_TIMEOUT_SECONDS = 15

# Access Point mode (Pico creates its own Wi-Fi)
AP_SSID = 'Pico2W-Setup'
AP_PASSWORD = 'pico2wsetup'  # minimum 8 chars for WPA2
AP_CHANNEL = 6

# NFC + cloud action settings
NFC_ENABLED = True
NFC_I2C_ID = 0
NFC_SCL_PIN = 21
NFC_SDA_PIN = 20
NFC_SCAN_POST_URL = "https://discord.com/api/webhooks/1482694832794239047/iSjdS865S_3q2y55Wp85CJv8pckvnXBZgXVMo4uXprZ92Shc4x5xjCO3x8aDU_CzDp_8"

