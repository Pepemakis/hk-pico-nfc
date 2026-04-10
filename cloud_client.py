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


def _open_connection(url, timeout_s):
    is_https, host, port, path = _parse_url(url)
    addr = socket.getaddrinfo(host, port)[0][-1]

    s = socket.socket()
    s.settimeout(timeout_s)
    conn = s
    try:
        s.connect(addr)
        conn = ssl.wrap_socket(s) if is_https else s
        return conn, s, host, path
    except Exception:
        try:
            conn.close()
        except OSError:
            pass
        try:
            s.close()
        except OSError:
            pass
        raise


def _read_until(conn, marker):
    data = b""
    while marker not in data:
        chunk = conn.read(256)
        if not chunk:
            break
        data += chunk
    return data


def _parse_response_head(head):
    status_line = head.split(b"\r\n", 1)[0].decode("utf-8", "ignore")
    status_code = 0
    parts = status_line.split(" ")
    if len(parts) >= 2:
        try:
            status_code = int(parts[1])
        except ValueError:
            status_code = 0
    return status_code, status_line


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
    conn, s, host, path = _open_connection(url, timeout_s)
    try:
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

        status_code, status_line = _parse_response_head(response)
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


def get_json(url, timeout_s=5):
    conn, s, host, path = _open_connection(url, timeout_s)
    try:
        req = (
            "GET {path} HTTP/1.1\r\n"
            "Host: {host}\r\n"
            "User-Agent: pico2w/1.0\r\n"
            "Accept: application/json\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).format(path=path, host=host)
        conn.write(req.encode())

        response = b""
        while True:
            chunk = conn.read(256)
            if not chunk:
                break
            response += chunk

        head, body = response.split(b"\r\n\r\n", 1)
        status_code, status_line = _parse_response_head(head)
        return status_code, status_line, json.loads(body.decode("utf-8"))
    finally:
        try:
            conn.close()
        except OSError:
            pass
        try:
            s.close()
        except OSError:
            pass


def download_file(url, tmp_path, timeout_s=10):
    conn, s, host, path = _open_connection(url, timeout_s)
    try:
        req = (
            "GET {path} HTTP/1.1\r\n"
            "Host: {host}\r\n"
            "User-Agent: pico2w/1.0\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).format(path=path, host=host)
        conn.write(req.encode())

        response_head = _read_until(conn, b"\r\n\r\n")
        if b"\r\n\r\n" not in response_head:
            raise OSError("HTTP response missing headers")

        head, initial_body = response_head.split(b"\r\n\r\n", 1)
        status_code, status_line = _parse_response_head(head)
        if not (200 <= status_code < 300):
            raise OSError(status_line)

        with open(tmp_path, "wb") as f:
            if initial_body:
                f.write(initial_body)

            while True:
                chunk = conn.read(512)
                if not chunk:
                    break
                f.write(chunk)

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
