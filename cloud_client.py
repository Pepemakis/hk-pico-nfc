try:
    import usocket as socket
except ImportError:
    import socket

try:
    import ussl as ssl
except ImportError:
    import ssl

import json


def _parse_url(url):
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("URL must start with http:// or https://")

    is_https = url.startswith("https://")
    rest = url[8:] if is_https else url[7:]

    if "/" in rest:
        host_port, path = rest.split("/", 1)
        path = "/" + path
    else:
        host_port = rest
        path = "/"

    if ":" in host_port:
        host, port_str = host_port.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_port
        port = 443 if is_https else 80

    return is_https, host, port, path


def _is_discord_webhook(url):
    return (
        "discord.com/api/webhooks/" in url
        or "discordapp.com/api/webhooks/" in url
    )


def _build_discord_payload(payload):
    device_id = payload.get("device_id", "")
    nfc_uid = payload.get("nfc_uid", "")
    flag = payload.get("flag", 0)
    state = "present" if flag else "removed"

    return {
        "content": (
            "NFC event\n"
            "device_id: {device_id}\n"
            "nfc_uid: {nfc_uid}\n"
            "flag: {flag} ({state})"
        ).format(
            device_id=device_id,
            nfc_uid=nfc_uid,
            flag=flag,
            state=state,
        )
    }


def post_json(url, payload, timeout_s=5):
    is_https, host, port, path = _parse_url(url)
    addr = socket.getaddrinfo(host, port)[0][-1]

    s = socket.socket()
    s.settimeout(timeout_s)
    conn = s
    try:
        s.connect(addr)
        conn = ssl.wrap_socket(s) if is_https else s

        body_payload = _build_discord_payload(payload) if _is_discord_webhook(url) else payload
        body = json.dumps(body_payload)
        req = (
            "POST {path} HTTP/1.1\r\n"
            "Host: {host}\r\n"
            "User-Agent: pico2w/1.0\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {length}\r\n"
            "Connection: close\r\n"
            "\r\n"
            "{body}"
        ).format(path=path, host=host, length=len(body), body=body)

        conn.write(req.encode())

        response = b""
        while True:
            chunk = conn.read(256)
            if not chunk:
                break
            response += chunk

        status_line = response.split(b"\r\n", 1)[0].decode("utf-8", "ignore")
        status_code = 0
        parts = status_line.split(" ")
        if len(parts) >= 2:
            try:
                status_code = int(parts[1])
            except ValueError:
                status_code = 0

        return status_code, status_line
    finally:
        try:
            conn.close()
        except OSError:
            pass
        try:
            s.close()
        except OSError:
            pass

