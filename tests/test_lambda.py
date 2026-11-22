"""Tests for the S3-triggered Lambda file processor (uses a fake S3 client)."""
import importlib.util
import json
from pathlib import Path

HANDLER_PATH = Path(__file__).resolve().parents[1] / "lambda" / "file_processor" / "handler.py"
EVENT_PATH = Path(__file__).resolve().parent / "events" / "s3_put.json"

_spec = importlib.util.spec_from_file_location("file_processor_handler", HANDLER_PATH)
handler_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler_module)


class FakeS3:
    def __init__(self, size=2048, content_type="image/png"):
        self.size = size
        self.content_type = content_type
        self.tags = {}

    def head_object(self, Bucket, Key):
        return {"ContentLength": self.size, "ContentType": self.content_type}

    def put_object_tagging(self, Bucket, Key, Tagging):
        self.tags[(Bucket, Key)] = {t["Key"]: t["Value"] for t in Tagging["TagSet"]}


def make_event(key, bucket="ticketdesk-attachments-test"):
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


def test_valid_file_is_tagged_processed():
    s3 = FakeS3()
    result = handler_module.handler(make_event("attachments/ticket-1/abc-screen.png"), None, s3=s3)
    assert result["processed"] == 1
    tags = s3.tags[("ticketdesk-attachments-test", "attachments/ticket-1/abc-screen.png")]
    assert tags["lambda-status"] == "processed"
    assert tags["size-bytes"] == "2048"
    assert tags["lambda-checked-at"].endswith("Z")


def test_url_encoded_keys_are_decoded():
    s3 = FakeS3()
    handler_module.handler(make_event("attachments/ticket-1/my+file%281%29.pdf"), None, s3=s3)
    assert ("ticketdesk-attachments-test", "attachments/ticket-1/my file(1).pdf") in s3.tags


def test_disallowed_extension_is_rejected():
    s3 = FakeS3()
    result = handler_module.handler(make_event("attachments/ticket-1/tool.exe"), None, s3=s3)
    assert result["results"][0]["status"] == "rejected"
    tags = s3.tags[("ticketdesk-attachments-test", "attachments/ticket-1/tool.exe")]
    assert tags["lambda-status"] == "rejected"
    assert "exe" in tags["lambda-reason"]


def test_empty_and_oversized_files_are_rejected():
    assert handler_module.inspect_file("a.png", 0)[0] == "rejected"
    assert handler_module.inspect_file("a.png", handler_module.MAX_SIZE_BYTES + 1)[0] == "rejected"
    assert handler_module.inspect_file("a.png", 10) == ("processed", "ok")


def test_tag_values_are_sanitised():
    assert handler_module._tag_value("extension (none) <bad>") == "extension none bad"


def test_sample_console_event_works():
    """tests/events/s3_put.json is the event to paste into the Lambda console 'Test' tab."""
    event = json.loads(EVENT_PATH.read_text())
    s3 = FakeS3(size=10, content_type="text/plain")
    assert handler_module.handler(event, None, s3=s3)["processed"] == 1
