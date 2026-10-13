import time, unittest
from unittest.mock import patch
from mrh.adapters.providers.typesafe import HttpTransport
from mrh.adapters.providers.typesafe_protocol import PINNED_MODEL

class HttpTransportTests(unittest.TestCase):
    def test_fixed_https_transport_certificate_deadline_size_and_cleanup(self):
        connection = unittest.mock.MagicMock()
        response = connection.getresponse.return_value
        response.status = 302
        response.read1.side_effect = [b"redirect", b""]
        context = object()
        with patch("mrh.adapters.providers.typesafe.ssl.create_default_context", return_value=context) as cert, \
             patch("mrh.adapters.providers.typesafe.http.client.HTTPSConnection", return_value=connection) as create:
            result = HttpTransport().request({"model": PINNED_MODEL}, {"Authorization": "Bearer fake"}, time.monotonic() + 1,
                                            lambda: (lambda: None))
        self.assertEqual(result.status, 302)
        cert.assert_called_once_with()
        args, kwargs = create.call_args
        self.assertEqual(args, ("api.typesafe.ai",))
        self.assertEqual(kwargs["port"], 443); self.assertIs(kwargs["context"], context)
        self.assertLessEqual(kwargs["timeout"], 1)
        self.assertEqual(connection.request.call_args.args[:2], ("POST", "/v1/systemone"))
        self.assertEqual(response.read1.call_args_list, [unittest.mock.call(65537), unittest.mock.call(65529)])
        connection.close.assert_called_once()
        with patch("mrh.adapters.providers.typesafe.http.client.HTTPSConnection") as create:
            with self.assertRaises(TimeoutError):
                HttpTransport().request({}, {}, time.monotonic() - 1, lambda: (lambda: None))
            create.assert_not_called()
