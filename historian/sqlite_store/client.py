"""One framed request per Unix socket connection; no client-selected authority."""

import json
import socket


def request(socket_path, operation, data):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(socket_path))
        connection.sendall(
            (json.dumps({"operation": operation, "data": data}) + "\n").encode()
        )
        with connection.makefile("rb") as stream:
            return json.loads(stream.readline())
