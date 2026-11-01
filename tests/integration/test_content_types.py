"""What kind of content an id is: the gateway asks `POST /api/v2/content/convert-ids-to-types`, in the real adapter and in the fake."""
import unittest

from conflu_c_cli.adapters.driven.confluence_rest import RestConfluenceGateway
from conflu_c_cli.adapters.driven.http_transport import HttpTransport
from conflu_c_cli.application.settings import Settings
from tests.support.fakes import FakeGateway
from tests.support.mock_confluence import MockConfluence


class ContentTypesTest(unittest.TestCase):
    def setUp(self):
        self.mock = MockConfluence()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        settings = Settings(base_url=self.mock.base_url, email=self.mock.email, api_token=self.mock.token, retry=0, connect_timeout=5.0, max_time=10.0)
        transport = HttpTransport(settings)
        self.addCleanup(transport.close)
        self.gateway = RestConfluenceGateway(settings, transport)

    def test_the_real_adapter_says_what_each_id_is(self):
        self.mock.content_kinds["7001"] = "folder"
        found = self.gateway.content_types(["2002", "4001", "4003", "7001", "99999"])
        self.assertEqual(found, {"2002": "page", "4001": "footer-comment", "4003": "inline-comment", "7001": "folder", "99999": None})
        sent = [item for item in self.mock.requests if item.path == "/api/v2/content/convert-ids-to-types"]
        self.assertEqual([item.method for item in sent], ["POST"])
        self.assertEqual(sent[0].body, {"contentIds": ["2002", "4001", "4003", "7001", "99999"]})
        self.assertEqual(self.mock.unknown_endpoints, [])
        self.assertEqual(self.mock.used_endpoints, ["POST /api/v2/content/convert-ids-to-types"])

    def test_more_than_a_hundred_ids_go_in_batches_and_an_id_is_asked_once(self):
        ids = [str(number) for number in range(30000, 30250)]
        found = self.gateway.content_types([*ids, "2002", "2002"])
        self.assertEqual(len(found), 251)
        self.assertEqual(found["2002"], "page")
        self.assertEqual(len([item for item in self.mock.requests if item.path.endswith("convert-ids-to-types")]), 3)

    def test_the_mock_refuses_a_bad_body(self):
        from conflu_c_cli.domain.errors import RejectedError

        with self.assertRaises(RejectedError):
            self.gateway._call("POST", "/api/v2/content/convert-ids-to-types", {"contentIds": []})

    def test_the_fake_knows_pages_and_the_content_that_a_test_registers(self):
        fake = FakeGateway()
        fake.content_kinds["7001"] = "folder"
        self.assertEqual(fake.content_types(["2002", "7001", "1"]), {"2002": "page", "7001": "folder", "1": None})
        self.assertEqual(fake.called("content_types"), [("content_types", ("2002", "7001", "1"))])


if __name__ == "__main__":
    unittest.main()
