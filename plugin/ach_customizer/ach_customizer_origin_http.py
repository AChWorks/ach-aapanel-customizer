"""Shared origin-local HTTPS transport for Cache observations.

Callers supply only validated native hostnames and fixed local paths.
No DNS resolution, remote redirects, user credentials or TLS bypass.
"""
import http.client
import socket
import ssl


def same_host_https_upgrade(hostname, path, status, location):
    return (status in (301, 302, 307, 308) and
            location in ('https://' + hostname + path,
                         'https://' + hostname + ':443' + path))


class LoopbackHTTPSConnection(http.client.HTTPConnection):
    """TLS to the local origin with the exact registered hostname as SNI."""

    def __init__(self, hostname, port, *, context, timeout=5):
        super().__init__(hostname, port, timeout=timeout)
        self.context = context

    def connect(self):
        raw = socket.create_connection(('127.0.0.1', self.port), self.timeout)
        try:
            self.sock = self.context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def https_connection(hostname, port=443, *, timeout=5, context=None):
    return LoopbackHTTPSConnection(
        hostname, port, timeout=timeout,
        context=context if context is not None else ssl.create_default_context())
