"""Default-off TypeSafe client. Construction does not resolve credentials."""
from dataclasses import dataclass
import http.client
import json
import os
import socket
import ssl
import time
from mrh.routing.core import ClassifierFailure
from mrh.adapters.providers.typesafe_protocol import PINNED_MODEL, parse_response, serialize_request

MAX_RESPONSE_BYTES = 65536


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


class HttpTransport:
    synthetic = False

    def request(self, body, headers, deadline, enter):
        check = enter()
        def remaining():
            check()
            value = deadline - time.monotonic()
            if value <= 0:
                raise TimeoutError()
            return value
        # The origin and path are fixed. stdlib HTTPConnection never follows a
        # redirect; no unverified host can receive this Authorization header.
        connection = http.client.HTTPSConnection("api.typesafe.ai", port=443,
                        timeout=min(2.0, remaining()), context=ssl.create_default_context())
        try:
            connection.connect()
            stream_socket = connection.sock
            stream_socket.settimeout(min(2.0, remaining()))
            connection.request("POST", "/v1/systemone", body=json.dumps(body, allow_nan=False).encode(), headers=headers)
            stream_socket.settimeout(min(2.0, remaining()))
            response = connection.getresponse()
            payload = bytearray()
            while True:
                stream_socket.settimeout(min(2.0, remaining()))
                chunk = response.read1(MAX_RESPONSE_BYTES + 1 - len(payload))
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise ClassifierFailure("typesafe_oversized_response")
            return HttpResponse(response.status, bytes(payload))
        finally:
            connection.close()


def environment_credential():
    """Future authorized runtime only; never evaluated before both gates."""
    return os.environ.get("TYPESAFE_API_KEY")


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


class TypesafeClassifier:
    def __init__(self, *, enabled=False, task_export_permitted=False, credential_resolver=None, transport=None):
        self.enabled = enabled is True
        self.task_export_permitted = task_export_permitted is True
        self.credential_resolver = credential_resolver or environment_credential
        self.transport = transport if transport is not None else HttpTransport()
        if type(self.transport) is HttpTransport:
            self.synthetic = False
        elif getattr(self.transport, "synthetic", None) is True:
            self.synthetic = True
        else:
            raise ClassifierFailure("typesafe_unverified_transport")

    def classify(self, task, context, recorder):
        if not self.enabled:
            raise ClassifierFailure("typesafe_disabled")
        if not self.task_export_permitted:
            raise ClassifierFailure("typesafe_export_denied")
        recorder.check()
        body = serialize_request(task, context)
        if len(json.dumps(body, allow_nan=False).encode()) > 65536:
            raise ClassifierFailure("typesafe_invalid_task")
        try:
            key = self.credential_resolver()
        except Exception:
            raise ClassifierFailure("typesafe_missing_credentials") from None
        if not isinstance(key, str) or not 0 < len(key) <= 2048 or any(not 33 <= ord(c) <= 126 for c in key):
            raise ClassifierFailure("typesafe_missing_credentials")
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        kind = "synthetic" if self.synthetic else "jev"
        def safe_telemetry(telemetry):
            result = dict(telemetry)
            model = result.get("response_model")
            if isinstance(model, str) and any(value and value in model for value in (key, task, context)):
                result["response_model"] = None
            return result
        try:
            response = recorder.invoke("0", lambda enter: self.transport.request(body, headers, recorder.deadline, enter),
                                       kind=kind, requested_model=PINNED_MODEL)
            if not isinstance(response, HttpResponse) or type(response.status) is not int or not isinstance(response.body, bytes):
                raise ClassifierFailure("typesafe_malformed_response")
            if 300 <= response.status < 400:
                raise ClassifierFailure("typesafe_redirect_rejected")
            if response.status != 200:
                code = "typesafe_http_" + str(response.status) if response.status in (401, 422, 429, 529) else "typesafe_http_5xx" if 500 <= response.status < 600 else "typesafe_http_error"
                raise ClassifierFailure(code)
            if len(response.body) > MAX_RESPONSE_BYTES:
                raise ClassifierFailure("typesafe_oversized_response")
            try:
                data = json.loads(response.body, object_pairs_hook=_no_duplicate_keys)
            except (ValueError, UnicodeError):
                raise ClassifierFailure("typesafe_malformed_response") from None
            parsed = parse_response(data)
            recorder.finish("0", "returned", **safe_telemetry(parsed.telemetry))
            return parsed.classification
        except ClassifierFailure as exc:
            # Parser telemetry is bounded and allowlisted. Store validates again.
            try:
                recorder.finish("0", "error", error_reason=exc.reason, **safe_telemetry(exc.telemetry))
            except ValueError:
                pass  # No started transport means no terminal transport fact.
            raise
        except (TimeoutError, socket.timeout):
            try:
                recorder.finish("0", "unknown", error_reason="typesafe_timeout")
            except ValueError:
                pass
            raise ClassifierFailure("typesafe_timeout") from None
        except Exception:
            try:
                recorder.finish("0", "error", error_reason="typesafe_network_error")
            except ValueError:
                pass
            raise ClassifierFailure("typesafe_network_error") from None


def classifier_from_config(config=None, **injected):
    config = {} if config is None else config
    if not isinstance(config, dict) or set(config) - {"schema_version", "enabled", "task_export_permitted", "model"}:
        raise ClassifierFailure("invalid_policy")
    if config.get("model", PINNED_MODEL) != PINNED_MODEL or config.get("schema_version", 1) != 1:
        raise ClassifierFailure("invalid_policy")
    if type(config.get("schema_version", 1)) is not int or any(type(config.get(field, False)) is not bool
                                                             for field in ("enabled", "task_export_permitted")):
        raise ClassifierFailure("invalid_policy")
    return TypesafeClassifier(enabled=config.get("enabled", False),
                             task_export_permitted=config.get("task_export_permitted", False), **injected)
