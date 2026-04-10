import socket


def html_escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def url_decode(text):
    text = text.replace("+", " ")
    out = []
    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        if ch == "%" and i + 2 < length:
            hex_code = text[i + 1 : i + 3]
            try:
                out.append(chr(int(hex_code, 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(ch)
        i += 1
    return "".join(out)


def parse_form_urlencoded(body):
    data = {}
    if not body:
        return data
    for pair in body.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
        else:
            key, value = pair, ""
        data[url_decode(key)] = url_decode(value)
    return data


def read_http_request(conn, max_bytes=4096):
    raw = b""
    while b"\r\n\r\n" not in raw and len(raw) < max_bytes:
        chunk = conn.recv(512)
        if not chunk:
            break
        raw += chunk

    if not raw:
        return "GET", "/", ""

    head, _, body_bytes = raw.partition(b"\r\n\r\n")
    head_text = head.decode("utf-8", "ignore")
    lines = head_text.split("\r\n")
    request_line = lines[0] if lines else "GET / HTTP/1.1"
    parts = request_line.split(" ")
    method = parts[0] if len(parts) >= 1 else "GET"
    path = parts[1] if len(parts) >= 2 else "/"

    content_length = 0
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() == "content-length":
            try:
                content_length = int(value.strip())
            except ValueError:
                content_length = 0
            break

    while len(body_bytes) < content_length and len(head) + 4 + len(body_bytes) < max_bytes:
        chunk = conn.recv(min(512, content_length - len(body_bytes)))
        if not chunk:
            break
        body_bytes += chunk

    body = body_bytes.decode("utf-8", "ignore")
    return method, path, body


def send_http_response(conn, body, status="200 OK", content_type="text/html; charset=utf-8"):
    response = (
        "HTTP/1.1 {status}\r\n"
        "Content-Type: {content_type}\r\n"
        "Content-Length: {length}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        "\r\n"
        "{body}"
    ).format(
        status=status,
        content_type=content_type,
        length=len(body),
        body=body,
    )
    conn.sendall(response)


def render_setup_page(ap_ssid, ap_ip, networks, message=""):
    options = []
    for ssid, rssi in networks:
        label = "{} ({})".format(html_escape(ssid), rssi)
        options.append('<option value="{}">{}</option>'.format(html_escape(ssid), label))
    options_html = "\n".join(options)
    message_html = ""
    if message:
        message_html = '<p class="msg">{}</p>'.format(html_escape(message))

    return """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Pico 2 W Setup</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; background:#f8fafc; color:#1f2937; }}
    .card {{ max-width: 620px; padding: 1rem 1.25rem; border: 1px solid #d1d5db; border-radius: 10px; background:#fff; }}
    h1 {{ margin-top: 0; }}
    label {{ display:block; margin-top:0.75rem; font-weight:600; }}
    input {{ width:100%; box-sizing:border-box; padding:0.55rem; margin-top:0.25rem; }}
    button {{ margin-top:1rem; padding:0.6rem 1rem; border:0; border-radius:6px; background:#0f766e; color:#fff; }}
    .muted {{ color:#6b7280; font-size:0.92rem; }}
    .msg {{ background:#ecfeff; border:1px solid #a5f3fc; padding:0.5rem; border-radius:6px; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Pico Wi-Fi Setup</h1>
    <p class="muted">Connected AP: <strong>{ap_ssid}</strong> | Device IP: <strong>{ap_ip}</strong></p>
    {message_html}
    <form method="post" action="/configure">
      <label for="ssid">Wi-Fi network (SSID)</label>
      <input id="ssid" name="ssid" list="ssid-list" placeholder="Enter or pick SSID" required>
      <datalist id="ssid-list">
        {options_html}
      </datalist>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" placeholder="Wi-Fi password" required>
      <button type="submit">Save & Connect</button>
    </form>
    <p class="muted">Credentials are saved on the Pico and reused after restart.</p>
  </div>
</body>
</html>
""".format(
        ap_ssid=html_escape(ap_ssid),
        ap_ip=html_escape(ap_ip),
        options_html=options_html,
        message_html=message_html,
    )


def render_saved_page(ssid):
    return """<!doctype html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Saved</title>
</head><body>
<h2>Saved</h2>
<p>SSID <strong>{ssid}</strong> saved. Pico will reboot and try to connect now.</p>
</body></html>""".format(ssid=html_escape(ssid))


def start_http_server():
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    server = socket.socket()
    try:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except OSError:
        pass
    server.bind(addr)
    server.listen(1)
    server.settimeout(0.05)
    print("HTTP server ready on port 80")
    return server


def serve_http_once(server, ap_ip, ap_ssid, scan_networks_fn, save_wifi_config_fn):
    try:
        conn, _ = server.accept()
    except OSError:
        return False

    try:
        conn.settimeout(0.5)
        try:
            method, path, body = read_http_request(conn)
        except OSError:
            return False
        print("HTTP request:", method, path)

        try:
            if method == "POST" and path.startswith("/configure"):
                form = parse_form_urlencoded(body)
                ssid = form.get("ssid", "").strip()
                password = form.get("password", "")

                if not ssid:
                    page = render_setup_page(ap_ssid, ap_ip, scan_networks_fn(), "SSID is required.")
                    send_http_response(conn, page)
                    return False

                if len(password) < 8:
                    page = render_setup_page(ap_ssid, ap_ip, scan_networks_fn(), "Password must be at least 8 characters.")
                    send_http_response(conn, page)
                    return False

                save_wifi_config_fn(ssid, password)
                print("Saved STA credentials for SSID:", ssid)
                send_http_response(conn, render_saved_page(ssid))
                return True

            page = render_setup_page(ap_ssid, ap_ip, scan_networks_fn())
            send_http_response(conn, page)
        except OSError:
            pass
        return False
    finally:
        try:
            conn.close()
        except OSError:
            pass

