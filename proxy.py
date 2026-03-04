import sys
import socket
import threading

MAX_WORKERS = 100
BUF_SIZE = 4096

active_workers = 0
worker_mutex = threading.Lock()


def extract_target(full_url):
    if not full_url.startswith("http://"):
        raise ValueError("bad url")

    trimmed = full_url[7:]
    port_index = trimmed.find(':')
    slash_index = trimmed.find('/')

    if slash_index == -1:
        slash_index = len(trimmed)

    if port_index != -1 and port_index < slash_index:
        hostname = trimmed[:port_index]
        portnum = int(trimmed[port_index + 1:slash_index])
    else:
        hostname = trimmed[:slash_index]
        portnum = 80

    resource = trimmed[slash_index:] if slash_index < len(trimmed) else "/"

    return hostname, portnum, resource


def decode_request(raw_bytes):
    text = raw_bytes.decode("utf-8", errors="ignore")
    segments = text.split("\r\n")

    if len(segments) == 0:
        raise ValueError("empty")

    first_line_parts = segments[0].split()
    if len(first_line_parts) != 3:
        raise ValueError("malformed")

    verb, full_url, proto = first_line_parts

    if proto not in ["HTTP/1.0", "HTTP/1.1"]:
        raise ValueError("unsupported")

    host, port, path = extract_target(full_url)

    header_blob = "\r\n".join(segments[1:]) + "\r\n"

    return verb, host, port, path, header_blob


def respond_error(sock, status_code, message):
    payload = f"HTTP/1.0 {status_code} {message}\r\nContent-Length: 0\r\n\r\n"
    sock.sendall(payload.encode())


def process_connection(client_fd):
    global active_workers

    incoming = b""

    while True:
        chunk = client_fd.recv(BUF_SIZE)
        if not chunk:
            break
        incoming += chunk
        if b"\r\n\r\n" in incoming:
            break

    if not incoming:
        client_fd.close()
        return

    try:
        method, server_host, server_port, endpoint, hdrs = decode_request(incoming)
    except Exception:
        respond_error(client_fd, 400, "bad request")
        client_fd.close()
        with worker_mutex:
            active_workers -= 1
        return

    if method != "GET":
        respond_error(client_fd, 501, "not implemented")
        client_fd.close()
        with worker_mutex:
            active_workers -= 1
        return

    remote_fd = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    remote_fd.connect((server_host, server_port))

    forward_packet = (
        f"GET {endpoint} HTTP/1.0\r\n"
        f"Host: {server_host}\r\n"
        f"{hdrs}\r\n"
    )

    remote_fd.sendall(forward_packet.encode())

    while True:
        reply = remote_fd.recv(BUF_SIZE)
        if not reply:
            break
        client_fd.sendall(reply)

    remote_fd.close()
    client_fd.close()

    with worker_mutex:
        active_workers -= 1


def launch():
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <port>")
        sys.exit(1)

    listen_port = int(sys.argv[1])

    master_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    master_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    master_socket.bind(("", listen_port))
    master_socket.listen(socket.SOMAXCONN)

    print("Syed Huzaifa Ali (23K-0004)")
    print(f"proxy running on port {listen_port}")

    global active_workers

    while True:
        client_socket, _ = master_socket.accept()

        with worker_mutex:
            if active_workers >= MAX_WORKERS:
                respond_error(client_socket, 503, "unavailable")
                client_socket.close()
                continue
            active_workers += 1

        worker = threading.Thread(target=process_connection, args=(client_socket,))
        worker.start()


if __name__ == "__main__":
    launch()