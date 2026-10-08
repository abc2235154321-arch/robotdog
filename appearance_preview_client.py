"""Bounded, proxy-free loopback HTTP client for the no-motion preview.

No ROS, GUI, motor actions or external network destinations.
"""
import http.client
import json
from urllib.parse import urlsplit

COLORS = ("red", "orange", "yellow", "green", "blue", "purple", "black", "white", "gray")


class PreviewClient:
    def __init__(self, url="http://127.0.0.1:8766"):
        value = urlsplit(url)
        if (value.scheme != "http" or value.hostname not in {"127.0.0.1", "localhost"}
                or value.username is not None or value.password is not None
                or value.path not in {"", "/"} or value.query or value.fragment):
            raise ValueError("Preview URL must be a local HTTP root address")
        self.host, self.port = value.hostname, value.port or 80
        if not 1 <= self.port <= 65535:
            raise ValueError("Invalid preview port")
        self.origin = f"http://{self.host}:{self.port}"

    def request(self, path, method="GET", body=None, maximum=2_000_000):
        if path not in {"/status.json", "/frame.jpg", "/raw.jpg", "/command"}:
            raise ValueError("Unsupported preview endpoint")
        connection = http.client.HTTPConnection(self.host, self.port, timeout=2)
        headers = {"Origin": self.origin, "Host": f"{self.host}:{self.port}"}
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode("utf-8")
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            content = response.read(maximum + 1)
            if len(content) > maximum:
                raise RuntimeError("Preview response too large")
            if response.status not in (200, 202):
                raise RuntimeError(f"Preview HTTP {response.status}: {content[:160].decode('utf-8', errors='replace')}")
            return content
        finally:
            connection.close()

    def status(self):
        value = json.loads(self.request("/status.json", maximum=128_000))
        if not isinstance(value, dict):
            raise ValueError("Invalid preview status")
        return value

    def jpeg(self, view="projected"):
        if view not in {"raw", "projected"}:
            raise ValueError("Unsupported preview view")
        return self.request("/raw.jpg" if view == "raw" else "/frame.jpg")

    def command(self, request):
        if not isinstance(request, dict):
            raise ValueError("Unsupported observation request")
        if not ((set(request) == {"color"} and request["color"] in COLORS)
                or (set(request) == {"reset"} and request["reset"] is True)):
            raise ValueError("Unsupported observation request")
        return self.request("/command", "POST", request, maximum=128_000)
