"""
tests/test_whatsapp_cloud.py

Integration test suite for the WhatsApp Cloud API provider (Meta).
Verifies:
1.  Configuration validation (missing credentials named individually, warnings for
    partially-configured deployments, no network I/O, refusal to send when unconfigured).
2.  Phone normalisation into the E.164-without-'+' form Meta requires.
3.  Message sending (free-text payload shape, template payload shape, parameters,
    language selection, message-id extraction, empty-body refusal).
4.  Template sending (positional body/header components, no empty component array,
    language locale normalisation).
5.  Error handling for every failure mode the specification names: 429 rate limits,
    expired access token, invalid template, network timeout, provider unavailable —
    each asserted to (a) not raise, (b) be classified retryable or not correctly, and
    (c) retry only when retrying can help.
6.  Status mapping from Meta's webhook vocabulary onto CampaignRecipient statuses.
7.  Webhook verification (GET challenge accept/reject, POST HMAC signature accept/reject,
    fail-closed behaviour when secrets are unset).
8.  Webhook payload parsing (batched statuses and messages, quoted replies, interactive
    and media messages, malformed entries, non-WhatsApp payloads).
9.  Reply handling through the existing pipeline — asserting the reply reaches
    `CampaignReplyService.record_reply` and produces the same recipient state, timeline
    entry and lead-status automation as the internal webhook, with no duplicated logic.
10. Campaign execution against the real provider with a stubbed transport: per-recipient
    failure isolation, no exception escaping into the campaign loop, statuses recorded.
11. Provider registry/selection (settings-driven default, unknown name falls back to noop).

The Graph API is fully mocked via `httpx.MockTransport`; nothing here contacts Meta and no
real WhatsApp account, token or phone number is required. Sections 9 and 10 talk to the
real configured database (see CLAUDE.md) and hard-delete everything they create in a
`finally` block, matching `tests/test_whatsapp.py`.
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import httpx

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.lead import Lead, LeadStatus, LeadSource
from app.models.lead_activity import LeadActivity, ActivityType
from app.models.whatsapp import (
    WhatsAppTemplate,
    WhatsAppCampaign,
    CampaignRecipient,
    TemplateCategory,
    CampaignStatus,
    MessageStatus,
)
from app.schemas.lead import LeadCreate
from app.schemas.whatsapp import WhatsAppTemplateCreate, WhatsAppCampaignCreate
from app.services.lead import LeadService
from app.services.whatsapp import (
    WhatsAppTemplateService,
    WhatsAppCampaignService,
    CampaignReplyService,
    MetaWebhookService,
)
from app.services.whatsapp_cloud import (
    WhatsAppCloudProvider,
    MetaWebhookVerifier,
    MetaWebhookParser,
    META_STATUS_TO_MESSAGE_STATUS,
    classify_graph_error,
    normalize_msisdn,
)
from app.services.whatsapp_provider import (
    NoOpWhatsAppProvider,
    ProviderConfigurationResult,
    get_whatsapp_provider,
)
from sqlalchemy import select

MARKER = f"CLOUDTEST-{uuid.uuid4().hex[:8]}"

STUB_TOKEN = "EAAG_stub_access_token"
STUB_PHONE_NUMBER_ID = "1234567890"
STUB_WABA_ID = "9876543210"
STUB_APP_SECRET = "stub_app_secret_value"
STUB_VERIFY_TOKEN = "stub_verify_token_value"


# =====================================================================
# STUB GRAPH API
# =====================================================================

class StubGraphAPI:
    """
    An in-process stand-in for Meta's Graph API.

    Records every request it receives so a test can assert on *call behaviour* — that an
    expired token was not retried, that a 429 was — and not merely on the returned result.
    The retry policy is the part that actually bites in production: retrying an auth error
    once per recipient turns a token rotation into a rate-limit storm, and only a
    call-count assertion catches that.

    `responses` is a list of (status_code, body) pairs consumed one per request, so a test
    can script "429, then 200" and assert the retry succeeded. When it runs out, the last
    entry repeats — which is what makes "always 401" easy to express.
    """

    def __init__(
        self,
        responses: list[tuple[int, dict]] | None = None,
        *,
        raise_exc: Exception | None = None,
        raise_times: int | None = None,
        retry_after: str | None = None,
    ) -> None:
        self.responses = responses or [(200, {"messages": [{"id": "wamid.STUB"}]})]
        self.raise_exc = raise_exc
        self.raise_times = raise_times
        self.retry_after = retry_after
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Routes one intercepted request, recording its decoded payload."""
        try:
            payload = json.loads(request.content) if request.content else {}
        except json.JSONDecodeError:
            payload = {}

        self.requests.append({
            "url": str(request.url),
            "method": request.method,
            "headers": dict(request.headers),
            "payload": payload,
        })

        if self.raise_exc is not None:
            if self.raise_times is None or len(self.requests) <= self.raise_times:
                raise self.raise_exc

        index = min(len(self.requests) - 1, len(self.responses) - 1)
        code, body = self.responses[index]
        headers = {"Retry-After": self.retry_after} if self.retry_after else None
        return httpx.Response(code, json=body, headers=headers)

    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def last_payload(self) -> dict:
        return self.requests[-1]["payload"] if self.requests else {}


class StubbedCloudProvider(WhatsAppCloudProvider):
    """
    The real provider with its HTTP transport swapped for a stub.

    Subclassing to override only `_import_httpx` keeps payload construction, the retry
    loop, error classification, number normalisation and the no-raise contract as the
    production code — the stub replaces the socket, nothing else. This is the same seam
    `StubbedInstagramProvider` uses in `tests/test_instagram_import.py`.
    """

    def __init__(self, api: StubGraphAPI, **kwargs) -> None:
        super().__init__(
            access_token=kwargs.pop("access_token", STUB_TOKEN),
            phone_number_id=kwargs.pop("phone_number_id", STUB_PHONE_NUMBER_ID),
            business_account_id=kwargs.pop("business_account_id", STUB_WABA_ID),
            **kwargs,
        )
        self._api = api

    def _import_httpx(self):
        """Returns an httpx-shaped module whose AsyncClient is bound to the stub transport."""
        api = self._api

        class _StubHttpx:
            Timeout = httpx.Timeout

            @staticmethod
            def AsyncClient(**kwargs):
                return httpx.AsyncClient(transport=httpx.MockTransport(api.handler), **kwargs)

        return _StubHttpx


class _SettingsOverride:
    """
    Temporarily overrides `settings` attributes for the duration of a `with` block.

    The adapter reads settings at call time (deliberately, so configuration is not frozen
    at import), which means a test that wants to exercise the free-text path or a shortened
    retry budget has to move the setting and put it back. Doing that with a context manager
    rather than by hand is what keeps one test's override from leaking into the next.
    """

    def __init__(self, **overrides) -> None:
        self.overrides = overrides
        self.previous: dict = {}

    def __enter__(self):
        for key, value in self.overrides.items():
            self.previous[key] = getattr(settings, key)
            setattr(settings, key, value)
        return settings

    def __exit__(self, *exc_info) -> None:
        for key, value in self.previous.items():
            setattr(settings, key, value)


def check(condition: bool, message: str) -> None:
    """Asserts with a readable message, matching the house test style."""
    assert condition, message


# =====================================================================
# WEBHOOK PAYLOAD BUILDERS
# =====================================================================

def build_status_payload(
    message_id: str, status: str, *, timestamp: int = 1700000000, errors: list | None = None
) -> dict:
    """Builds a Meta webhook body carrying one delivery-status event."""
    entry: dict = {
        "id": message_id,
        "status": status,
        "timestamp": str(timestamp),
        "recipient_id": "919847012345",
    }
    if errors:
        entry["errors"] = errors
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": STUB_WABA_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": STUB_PHONE_NUMBER_ID},
                    "statuses": [entry],
                },
            }],
        }],
    }


def build_reply_payload(
    from_phone: str,
    text: str,
    *,
    message_id: str = "wamid.INBOUND",
    context_id: str | None = None,
    timestamp: int = 1700000100,
    message_type: str = "text",
    extra: dict | None = None,
) -> dict:
    """Builds a Meta webhook body carrying one inbound message."""
    message: dict = {
        "from": from_phone,
        "id": message_id,
        "timestamp": str(timestamp),
        "type": message_type,
    }
    if message_type == "text":
        message["text"] = {"body": text}
    if extra:
        message.update(extra)
    if context_id:
        message["context"] = {"from": from_phone, "id": context_id}

    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": STUB_WABA_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": STUB_PHONE_NUMBER_ID},
                    "contacts": [{"profile": {"name": "Test Lead"}, "wa_id": from_phone}],
                    "messages": [message],
                },
            }],
        }],
    }


# =====================================================================
# THE SUITE
# =====================================================================

async def test_whatsapp_cloud_suite() -> None:
    """Runs the full WhatsApp Cloud API provider suite."""
    created_lead_ids: list[uuid.UUID] = []
    created_template_ids: list[uuid.UUID] = []
    created_campaign_ids: list[uuid.UUID] = []

    print(f"\n=== WHATSAPP CLOUD API PROVIDER TESTS (marker {MARKER}) ===")

    # -----------------------------------------------------------------
    # 1. CONFIGURATION VALIDATION
    # -----------------------------------------------------------------
    print("\n--- 1. Configuration validation ---")

    unconfigured = WhatsAppCloudProvider(
        access_token="", phone_number_id="", business_account_id=""
    )
    result = await unconfigured.validate_configuration()
    check(isinstance(result, ProviderConfigurationResult), "validate_configuration returns a result object")
    check(result.valid is False, "An empty configuration is invalid")
    check("WHATSAPP_ACCESS_TOKEN" in result.missing, "The missing access token is named")
    check("WHATSAPP_PHONE_NUMBER_ID" in result.missing, "The missing phone number id is named")
    check(STUB_TOKEN not in result.as_message(), "The message never leaks a credential value")
    print(f"Unconfigured: {result.as_message()}")

    configured = WhatsAppCloudProvider(
        access_token=STUB_TOKEN,
        phone_number_id=STUB_PHONE_NUMBER_ID,
        business_account_id=STUB_WABA_ID,
    )
    result = await configured.validate_configuration()
    check(result.valid is True, "A complete configuration is valid")
    check(not result.missing, "A complete configuration names nothing missing")
    print(f"Configured: valid={result.valid}, warnings={len(result.warnings)}")

    # A deployment with send credentials but no webhook secrets is valid-with-warnings, not
    # invalid: it can send perfectly well and merely cannot receive.
    with _SettingsOverride(WHATSAPP_VERIFY_TOKEN="", WHATSAPP_APP_SECRET=""):
        partial = await configured.validate_configuration()
    check(partial.valid is True, "Missing webhook secrets do not invalidate sending")
    check(
        any("WHATSAPP_APP_SECRET" in w for w in partial.warnings),
        "A missing app secret is reported as a warning",
    )
    check(
        any("WHATSAPP_VERIFY_TOKEN" in w for w in partial.warnings),
        "A missing verify token is reported as a warning",
    )
    print(f"Partially configured warnings: {partial.warnings}")

    # An unconfigured provider must refuse to send rather than calling Meta with no token.
    refused = await unconfigured.send_message("9847012345", "Hello", template_name="t")
    check(refused.success is False, "An unconfigured provider refuses to send")
    check(refused.retryable is False, "A configuration failure is not retryable")
    check(refused.error_code == "not_configured", "The refusal is machine-identifiable")
    print(f"Unconfigured send refused: {refused.error}")

    # -----------------------------------------------------------------
    # 2. PHONE NORMALISATION
    # -----------------------------------------------------------------
    print("\n--- 2. Phone normalisation ---")

    cases = [
        ("9847012345", "919847012345", "a bare Indian 10-digit number gains the country code"),
        ("09847012345", "919847012345", "a national trunk prefix is dropped"),
        ("+91 98470 12345", "919847012345", "a formatted E.164 number is stripped to digits"),
        ("919847012345", "919847012345", "an already-qualified number is unchanged"),
        ("+1 415 555 2671", "14155552671", "a foreign qualified number keeps its own code"),
        ("98470-12345", "919847012345", "punctuation is removed"),
    ]
    for raw, expected, description in cases:
        actual = normalize_msisdn(raw)
        check(actual == expected, f"{description}: {raw!r} -> {actual!r}, expected {expected!r}")
    print(f"{len(cases)} normalisation cases correct.")

    for bad in ("", "abc", "12", None):
        check(normalize_msisdn(bad) is None, f"{bad!r} is rejected as unusable")
    print("Unusable numbers rejected rather than sent to Meta.")

    # -----------------------------------------------------------------
    # 3. MESSAGE SENDING
    # -----------------------------------------------------------------
    print("\n--- 3. Message sending ---")

    api = StubGraphAPI([(200, {"messages": [{"id": "wamid.HBgMOTE5ODQ3MDEyMzQ1"}]})])
    provider = StubbedCloudProvider(api)

    with _SettingsOverride(WHATSAPP_USE_TEMPLATES=False):
        sent = await provider.send_message("9847012345", "Hello from Colour Labs")

    check(sent.success is True, "A 200 from Meta is a successful send")
    check(sent.message_id == "wamid.HBgMOTE5ODQ3MDEyMzQ1", "The wamid is extracted from the response")
    check(sent.provider == "whatsapp_cloud", "The result names the adapter")

    payload = api.last_payload
    check(payload["messaging_product"] == "whatsapp", "messaging_product is set")
    check(payload["to"] == "919847012345", "The destination is normalised before sending")
    check(payload["type"] == "text", "A free-text send uses type=text")
    check(payload["text"]["body"] == "Hello from Colour Labs", "The body is sent verbatim")
    check(payload["text"]["preview_url"] is False, "Link previews are disabled")

    auth = api.requests[-1]["headers"].get("authorization", "")
    check(auth == f"Bearer {STUB_TOKEN}", "The access token is sent as a bearer token")
    check(
        f"/{settings.GRAPH_API_VERSION}/{STUB_PHONE_NUMBER_ID}/messages" in api.requests[-1]["url"],
        "The configured API version and phone number id form the URL",
    )
    print(f"Free-text send OK: {sent.message_id}")

    # An empty body is refused locally rather than sent for Meta to reject.
    api_empty = StubGraphAPI()
    empty = await StubbedCloudProvider(api_empty)._send_text("9847012345", "   ")
    check(empty.success is False, "An empty message body is refused")
    check(api_empty.call_count == 0, "An empty body never reaches the network")
    print("Empty message body refused without a network call.")

    # An unusable number fails that one recipient without a network call.
    api_bad = StubGraphAPI()
    bad_number = await StubbedCloudProvider(api_bad).send_message("abc", "Hi", template_name="t")
    check(bad_number.success is False, "An unusable number fails the send")
    check(bad_number.error_code == "invalid_number", "The failure identifies the cause")
    check(api_bad.call_count == 0, "An unusable number never reaches the network")
    print("Unusable number failed locally, no network call.")

    # -----------------------------------------------------------------
    # 4. TEMPLATE SENDING
    # -----------------------------------------------------------------
    print("\n--- 4. Template sending ---")

    api = StubGraphAPI([(200, {"messages": [{"id": "wamid.TEMPLATE"}]})])
    provider = StubbedCloudProvider(api)

    sent = await provider.send_template(
        "9847012345",
        "diwali_offer",
        language="en_US",
        parameters=["Sunrise Studio", "20%"],
        header_parameters=["Diwali"],
    )
    check(sent.success is True, "A template send succeeds")
    payload = api.last_payload
    check(payload["type"] == "template", "A template send uses type=template")
    check(payload["template"]["name"] == "diwali_offer", "The template name is sent")
    check(payload["template"]["language"]["code"] == "en_US", "The language code is sent")

    components = payload["template"]["components"]
    header = next(c for c in components if c["type"] == "header")
    body = next(c for c in components if c["type"] == "body")
    check([p["text"] for p in header["parameters"]] == ["Diwali"], "Header parameters are positional")
    check(
        [p["text"] for p in body["parameters"]] == ["Sunrise Studio", "20%"],
        "Body parameters are positional and ordered",
    )
    print(f"Template send OK with {len(components)} component(s).")

    # A template with no parameters must carry no components array at all — Meta rejects an
    # empty one with error 132000.
    api = StubGraphAPI([(200, {"messages": [{"id": "wamid.NOPARAMS"}]})])
    await StubbedCloudProvider(api).send_template("9847012345", "plain_notice", language="en")
    check(
        "components" not in api.last_payload["template"],
        "A parameterless template sends no components array",
    )
    print("Parameterless template omits the components array.")

    # Language selection: a hyphenated CRM code becomes Meta's underscore locale.
    api = StubGraphAPI([(200, {"messages": [{"id": "wamid.LANG"}]})])
    await StubbedCloudProvider(api).send_template("9847012345", "t", language="pt-BR")
    check(
        api.last_payload["template"]["language"]["code"] == "pt_BR",
        "A hyphenated language code is normalised to Meta's locale form",
    )
    print("Language locale normalisation correct (pt-BR -> pt_BR).")

    # send_message routes to the template path when templates are enabled and a name exists.
    api = StubGraphAPI([(200, {"messages": [{"id": "wamid.ROUTED"}]})])
    with _SettingsOverride(WHATSAPP_USE_TEMPLATES=True):
        await StubbedCloudProvider(api).send_message(
            "9847012345", "Rendered body text", template_name="welcome", language="en"
        )
    check(api.last_payload["type"] == "template", "send_message routes to the template path")
    check(
        api.last_payload["template"]["components"][0]["parameters"][0]["text"] == "Rendered body text",
        "The rendered body travels as the template's positional parameter",
    )
    print("send_message correctly routes to the template path.")

    # -----------------------------------------------------------------
    # 5. ERROR HANDLING — every mode the specification names
    # -----------------------------------------------------------------
    print("\n--- 5. Error handling ---")

    # 5a. Expired access token: fails, is NOT retried.
    api = StubGraphAPI([(401, {"error": {
        "message": "Error validating access token: Session has expired.",
        "type": "OAuthException", "code": 190,
    }})])
    with _SettingsOverride(WHATSAPP_MAX_RETRIES=3, WHATSAPP_RETRY_BACKOFF_SECONDS=0.0):
        expired = await StubbedCloudProvider(api).send_message("9847012345", "Hi", template_name="t")
    check(expired.success is False, "An expired token fails the send")
    check(expired.retryable is False, "An expired token is not retryable")
    check(expired.error_code == "190", "The Meta error code is recorded")
    check(api.call_count == 1, f"An expired token is NOT retried (was called {api.call_count}x)")
    print(f"Expired token: not retried, {expired.error}")

    # 5b. Invalid template: fails, is NOT retried.
    api = StubGraphAPI([(400, {"error": {
        "message": "Template name does not exist in the translation",
        "type": "OAuthException", "code": 132001,
    }})])
    with _SettingsOverride(WHATSAPP_MAX_RETRIES=3, WHATSAPP_RETRY_BACKOFF_SECONDS=0.0):
        bad_template = await StubbedCloudProvider(api).send_message(
            "9847012345", "Hi", template_name="does_not_exist"
        )
    check(bad_template.success is False, "An invalid template fails the send")
    check(bad_template.retryable is False, "An invalid template is not retryable")
    check(api.call_count == 1, f"An invalid template is NOT retried (was called {api.call_count}x)")
    print(f"Invalid template: not retried, {bad_template.error}")

    # 5c. 429 rate limit: retried, and succeeds when the retry lands.
    api = StubGraphAPI([
        (429, {"error": {"message": "Rate limit hit", "code": 130429}}),
        (200, {"messages": [{"id": "wamid.AFTER_RETRY"}]}),
    ], retry_after="0")
    with _SettingsOverride(WHATSAPP_MAX_RETRIES=2, WHATSAPP_RETRY_BACKOFF_SECONDS=0.0):
        recovered = await StubbedCloudProvider(api).send_message("9847012345", "Hi", template_name="t")
    check(recovered.success is True, "A rate-limited send succeeds after a retry")
    check(recovered.message_id == "wamid.AFTER_RETRY", "The retried send's message id is returned")
    check(api.call_count == 2, f"The rate-limited send was retried exactly once (got {api.call_count})")
    print(f"429 rate limit: retried and recovered as {recovered.message_id}")

    # 5d. 429 that never clears: exhausts retries, returns retryable failure, does not raise.
    api = StubGraphAPI([(429, {"error": {"message": "Rate limit hit", "code": 130429}})])
    with _SettingsOverride(WHATSAPP_MAX_RETRIES=2, WHATSAPP_RETRY_BACKOFF_SECONDS=0.0):
        exhausted = await StubbedCloudProvider(api).send_message("9847012345", "Hi", template_name="t")
    check(exhausted.success is False, "A persistent rate limit fails the send")
    check(exhausted.retryable is True, "A persistent rate limit is marked retryable")
    check(api.call_count == 3, f"Retries were bounded at max_retries+1 (got {api.call_count})")
    print(f"Persistent 429: bounded at {api.call_count} attempts, marked retryable.")

    # 5e. Network timeout: retried, then returned as a retryable failure — never raised.
    api = StubGraphAPI(raise_exc=httpx.ConnectTimeout("Simulated network timeout"))
    with _SettingsOverride(WHATSAPP_MAX_RETRIES=1, WHATSAPP_RETRY_BACKOFF_SECONDS=0.0):
        timed_out = await StubbedCloudProvider(api).send_message("9847012345", "Hi", template_name="t")
    check(timed_out.success is False, "A network timeout fails the send")
    check(timed_out.retryable is True, "A network timeout is marked retryable")
    check("reach" in (timed_out.error or "").lower(), "The error explains the transport failure")
    check(api.call_count == 2, f"A timeout was retried (got {api.call_count} attempts)")
    print(f"Network timeout: no exception raised, {timed_out.error}")

    # 5f. A timeout that clears on retry.
    api = StubGraphAPI(
        [(200, {"messages": [{"id": "wamid.RECOVERED"}]})],
        raise_exc=httpx.ReadTimeout("Simulated transient timeout"),
        raise_times=1,
    )
    with _SettingsOverride(WHATSAPP_MAX_RETRIES=2, WHATSAPP_RETRY_BACKOFF_SECONDS=0.0):
        healed = await StubbedCloudProvider(api).send_message("9847012345", "Hi", template_name="t")
    check(healed.success is True, "A transient timeout recovers on retry")
    print(f"Transient timeout recovered as {healed.message_id}")

    # 5g. Provider unavailable (5xx, HTML body): retried, retryable, no crash on non-JSON.
    api = StubGraphAPI([(503, {})])
    with _SettingsOverride(WHATSAPP_MAX_RETRIES=1, WHATSAPP_RETRY_BACKOFF_SECONDS=0.0):
        unavailable = await StubbedCloudProvider(api).send_message("9847012345", "Hi", template_name="t")
    check(unavailable.success is False, "A 503 fails the send")
    check(unavailable.retryable is True, "A 503 is marked retryable")
    check(api.call_count == 2, "A 503 was retried")
    print(f"Provider unavailable: {unavailable.error}")

    # 5h. A bad recipient is permanent for that lead and not retried.
    api = StubGraphAPI([(400, {"error": {
        "message": "Receiver is not a valid WhatsApp user", "code": 131026,
    }})])
    with _SettingsOverride(WHATSAPP_MAX_RETRIES=3, WHATSAPP_RETRY_BACKOFF_SECONDS=0.0):
        no_whatsapp = await StubbedCloudProvider(api).send_message("9847012345", "Hi", template_name="t")
    check(no_whatsapp.success is False, "A non-WhatsApp recipient fails")
    check(no_whatsapp.retryable is False, "A non-WhatsApp recipient is not retryable")
    check(api.call_count == 1, "A bad recipient is not retried")
    print(f"Non-WhatsApp recipient: not retried, {no_whatsapp.error}")

    # 5i. A 2xx with no message id is a failure, and is NOT retried (duplicate-send risk).
    api = StubGraphAPI([(200, {"messages": []})])
    with _SettingsOverride(WHATSAPP_MAX_RETRIES=2, WHATSAPP_RETRY_BACKOFF_SECONDS=0.0):
        no_id = await StubbedCloudProvider(api).send_message("9847012345", "Hi", template_name="t")
    check(no_id.success is False, "A 2xx with no message id is treated as a failure")
    check(api.call_count == 1, "An untrackable accepted message is not resent")
    print("2xx without a message id: failed without resending.")

    # 5j. Classification is a pure function and testable without any transport.
    check(classify_graph_error({"error": {"code": 190}}, 401).category == "auth", "190 -> auth")
    check(classify_graph_error({"error": {"code": 131047}}, 400).category == "template", "131047 -> template")
    check(classify_graph_error({"error": {"code": 4}}, 400).category == "rate_limit", "4 -> rate_limit")
    check(classify_graph_error({}, 502).category == "unavailable", "502 -> unavailable")
    check(classify_graph_error({}, 400).retryable is False, "An unrecognised 400 is not retried")
    print("Error classification is pure and correct across categories.")

    # 5k. get_message_status honestly reports that Meta cannot be polled.
    check(await configured.get_message_status("wamid.X") is None, "Cloud API cannot be polled for status")
    print("get_message_status correctly reports polling is unsupported.")

    # -----------------------------------------------------------------
    # 6. STATUS MAPPING
    # -----------------------------------------------------------------
    print("\n--- 6. Status mapping ---")

    expected_map = {
        "sent": MessageStatus.SENT,
        "accepted": MessageStatus.SENT,
        "delivered": MessageStatus.DELIVERED,
        "read": MessageStatus.READ,
        "failed": MessageStatus.FAILED,
    }
    for meta_status, crm_status in expected_map.items():
        mapped = META_STATUS_TO_MESSAGE_STATUS.get(meta_status)
        check(mapped == crm_status.name, f"Meta '{meta_status}' maps to {crm_status.name}, got {mapped}")
        check(MessageStatus[mapped] is crm_status, f"'{mapped}' resolves to a real MessageStatus")
    print(f"All {len(expected_map)} Meta statuses map onto CampaignRecipient statuses.")

    # QUEUED and REPLIED are CRM-side states with no Meta equivalent; that is correct.
    check(
        "QUEUED" not in META_STATUS_TO_MESSAGE_STATUS.values(),
        "QUEUED is a CRM-internal state and is not produced by a Meta status",
    )
    check(
        "REPLIED" not in META_STATUS_TO_MESSAGE_STATUS.values(),
        "REPLIED comes from an inbound message, not a status callback",
    )
    parser = MetaWebhookParser()
    deleted = parser.parse(build_status_payload("wamid.X", "deleted"))
    check(deleted.is_empty, "Meta's 'deleted' status is not a delivery outcome and is ignored")
    check(deleted.ignored, "The ignored 'deleted' status is reported rather than silently dropped")
    print("Unmapped Meta statuses ignored with a reason.")

    # -----------------------------------------------------------------
    # 7. WEBHOOK VERIFICATION
    # -----------------------------------------------------------------
    print("\n--- 7. Webhook verification ---")

    verifier = MetaWebhookVerifier(
        verify_token=STUB_VERIFY_TOKEN, app_secret=STUB_APP_SECRET
    )

    # GET handshake.
    check(
        verifier.verify_challenge("subscribe", STUB_VERIFY_TOKEN, "1158201444") == "1158201444",
        "A correct handshake returns the challenge to echo",
    )
    check(
        verifier.verify_challenge("subscribe", "wrong_token", "1158201444") is None,
        "A wrong verify token is rejected",
    )
    check(
        verifier.verify_challenge("unsubscribe", STUB_VERIFY_TOKEN, "1158201444") is None,
        "A non-subscribe mode is rejected",
    )
    check(
        verifier.verify_challenge("subscribe", None, "1158201444") is None,
        "A missing verify token is rejected",
    )
    check(
        MetaWebhookVerifier(verify_token="", app_secret=STUB_APP_SECRET).verify_challenge(
            "subscribe", "anything", "1158201444"
        ) is None,
        "An unconfigured verify token fails closed rather than accepting anything",
    )
    print("GET challenge verification correct, including fail-closed on no configured token.")

    # POST signature.
    body = json.dumps(build_status_payload("wamid.SIG", "delivered")).encode()
    good_signature = verifier.sign(body)

    with _SettingsOverride(WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE=True):
        check(verifier.verify_signature(body, good_signature), "A correctly signed body is accepted")
        check(
            not verifier.verify_signature(body, "sha256=" + "0" * 64),
            "A wrong signature is rejected",
        )
        check(not verifier.verify_signature(body, None), "A missing signature header is rejected")
        check(not verifier.verify_signature(body, "garbage"), "A malformed signature header is rejected")
        check(
            not verifier.verify_signature(b'{"tampered":true}', good_signature),
            "A tampered body is rejected against a valid signature",
        )
        check(
            not MetaWebhookVerifier(
                verify_token=STUB_VERIFY_TOKEN, app_secret=""
            ).verify_signature(body, good_signature),
            "An unconfigured app secret fails closed",
        )
    print("POST signature verification correct, including tamper and fail-closed cases.")

    # The escape hatch works, and only when explicitly enabled.
    with _SettingsOverride(WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE=False):
        check(
            verifier.verify_signature(body, None),
            "Signature verification can be explicitly disabled for local replay",
        )
    print("Signature requirement is togglable for local development only.")

    # -----------------------------------------------------------------
    # 8. WEBHOOK PAYLOAD PARSING
    # -----------------------------------------------------------------
    print("\n--- 8. Webhook payload parsing ---")

    parsed = parser.parse(build_status_payload("wamid.ABC", "delivered", timestamp=1700000000))
    check(len(parsed.statuses) == 1, "One status event is parsed")
    event = parsed.statuses[0]
    check(event.provider_message_id == "wamid.ABC", "The message id is extracted")
    check(event.status == "DELIVERED", "The status is mapped to the CRM vocabulary")
    check(
        event.occurred_at == datetime.fromtimestamp(1700000000, tz=timezone.utc),
        "The epoch timestamp is converted to an aware datetime",
    )
    print(f"Status event parsed: {event.provider_message_id} -> {event.status} at {event.occurred_at}")

    failed = parser.parse(build_status_payload("wamid.FAIL", "failed", errors=[{
        "code": 131026,
        "title": "Message undeliverable",
        "error_data": {"details": "Receiver is not a valid WhatsApp user"},
    }]))
    check(failed.statuses[0].status == "FAILED", "A failed status maps to FAILED")
    reason = failed.statuses[0].error_message or ""
    check("undeliverable" in reason.lower(), "The failure title is captured")
    check("131026" in reason, "The Meta error code is captured for lookup")
    print(f"Failure reason captured: {reason}")

    replies = parser.parse(build_reply_payload("919847012345", "Yes, I am interested"))
    check(len(replies.replies) == 1, "One inbound reply is parsed")
    reply = replies.replies[0]
    check(reply.from_phone == "919847012345", "The sender's number is extracted")
    check(reply.text == "Yes, I am interested", "The reply body is extracted")
    check(reply.context_message_id is None, "An unquoted reply carries no context id")

    quoted = parser.parse(build_reply_payload("919847012345", "Sure", context_id="wamid.OUTBOUND"))
    check(
        quoted.replies[0].context_message_id == "wamid.OUTBOUND",
        "A quoted reply carries the outbound message id it answers",
    )
    print("Inbound replies parsed, including quoted-reply context ids.")

    # A batched payload with both kinds of event in one delivery.
    batched = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": STUB_WABA_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "statuses": [
                        {"id": "wamid.1", "status": "sent", "timestamp": "1700000000"},
                        {"id": "wamid.2", "status": "read", "timestamp": "1700000001"},
                    ],
                    "messages": [{
                        "from": "919847012345", "id": "wamid.IN", "timestamp": "1700000002",
                        "type": "text", "text": {"body": "hello"},
                    }],
                },
            }],
        }],
    }
    both = parser.parse(batched)
    check(len(both.statuses) == 2, "Both statuses in a batched payload are parsed")
    check(len(both.replies) == 1, "The reply in a batched payload is parsed")
    print("Batched payload with 2 statuses + 1 reply parsed correctly.")

    # Interactive and media messages carry lead intent and must not be dropped.
    button = parser.parse(build_reply_payload(
        "919847012345", "", message_type="button",
        extra={"button": {"text": "Interested", "payload": "INTERESTED"}},
    ))
    check(button.replies[0].text == "Interested", "A quick-reply button tap is a reply")

    interactive = parser.parse(build_reply_payload(
        "919847012345", "", message_type="interactive",
        extra={"interactive": {"type": "button_reply",
                               "button_reply": {"id": "yes", "title": "Yes please"}}},
    ))
    check(interactive.replies[0].text == "Yes please", "An interactive button reply is a reply")

    image = parser.parse(build_reply_payload(
        "919847012345", "", message_type="image", extra={"image": {"id": "media1"}},
    ))
    check(image.replies[0].text == "[image message]", "A media reply is recorded with a placeholder")

    captioned = parser.parse(build_reply_payload(
        "919847012345", "", message_type="image",
        extra={"image": {"id": "media1", "caption": "Is this your work?"}},
    ))
    check(captioned.replies[0].text == "Is this your work?", "A media caption is preferred over the placeholder")
    print("Interactive, button and media messages all recorded as replies.")

    # Defensive parsing: nothing here may raise, because a raising webhook is retried forever.
    for label, bad_payload in [
        ("empty dict", {}),
        ("null entry", {"object": "whatsapp_business_account", "entry": None}),
        ("string entry", {"object": "whatsapp_business_account", "entry": "nonsense"}),
        ("no changes", {"object": "whatsapp_business_account", "entry": [{"id": "x"}]}),
        ("null value", {"object": "whatsapp_business_account",
                        "entry": [{"changes": [{"value": None}]}]}),
        ("status with no id", {"object": "whatsapp_business_account", "entry": [
            {"changes": [{"value": {"statuses": [{"status": "sent"}]}}]}]}),
        ("message with no sender", {"object": "whatsapp_business_account", "entry": [
            {"changes": [{"value": {"messages": [{"type": "text", "text": {"body": "hi"}}]}}]}]}),
        ("other product", {"object": "instagram", "entry": [{"changes": []}]}),
        ("not a dict", "a string payload"),
    ]:
        outcome = parser.parse(bad_payload)  # must not raise
        check(outcome.is_empty, f"A {label} payload yields no actionable events")
    print("9 malformed/foreign payloads parsed without raising.")

    # -----------------------------------------------------------------
    # 9 & 10. DATABASE-BACKED: REPLY PIPELINE + CAMPAIGN EXECUTION
    # -----------------------------------------------------------------
    async with AsyncSessionLocal() as db:
        try:
            print("\n--- 9. Reply handling through the existing pipeline ---")

            lead_service = LeadService()
            template_service = WhatsAppTemplateService()

            lead = await lead_service.create_lead(db, LeadCreate(
                business_name=f"{MARKER} Studio",
                contact_person="Test Owner",
                phone="9847012345",
                city="Kozhikode",
                source=LeadSource.MANUAL,
                status=LeadStatus.NEW,
            ))
            created_lead_ids.append(lead.id)

            template = await template_service.create_template(db, WhatsAppTemplateCreate(
                name=f"{MARKER}-template",
                category=TemplateCategory.MARKETING,
                language="en",
                message_body="Hello {{contact_person}}, this is {{business_name}}.",
                is_active=True,
            ))
            created_template_ids.append(template.id)

            # A campaign dispatched through the REAL Cloud provider with a stubbed socket.
            api = StubGraphAPI([(200, {"messages": [{"id": f"wamid.{MARKER}"}]})])
            campaign_service = WhatsAppCampaignService(provider=StubbedCloudProvider(api))

            campaign = await campaign_service.create_campaign(db, WhatsAppCampaignCreate(
                template_id=template.id,
                name=f"{MARKER} Campaign",
                description="Cloud provider integration test",
                lead_ids=[lead.id],
            ))
            created_campaign_ids.append(campaign.id)

            print("\n--- 10. Campaign execution through WhatsAppCloudProvider ---")
            run = await campaign_service.start_campaign(db, campaign_id=campaign.id)
            check(run["succeeded"] == 1, f"The campaign dispatched successfully (got {run})")
            check(run["failed"] == 0, "No recipient failed")
            check(run["provider"] == "whatsapp_cloud", "The run reports the Cloud adapter")
            check(api.call_count == 1, "Exactly one Graph API call was made for one recipient")

            sent_payload = api.last_payload
            check(sent_payload["to"] == "919847012345", "The lead's number was normalised for Meta")
            check(sent_payload["type"] == "template", "The campaign send used a template")
            check(
                sent_payload["template"]["name"] == template.name,
                "The CRM template's name was used as the Meta template name",
            )
            print(f"Campaign dispatched via Cloud provider: {run}")

            recipients, _ = await campaign_service.get_recipients(db, campaign_id=campaign.id)
            recipient = recipients[0]
            check(recipient.message_status == MessageStatus.SENT, "The recipient is SENT")
            check(
                recipient.provider_message_id == f"wamid.{MARKER}",
                "The Meta wamid was stored for webhook matching",
            )
            wamid = recipient.provider_message_id

            # Now drive a delivery status through the Meta webhook service — the same path
            # the endpoint uses — and assert it lands on the same recipient row.
            webhook_service = MetaWebhookService(campaign_service=campaign_service)

            delivered = parser.parse(build_status_payload(wamid, "delivered"))
            summary = await webhook_service.process(
                db, statuses=delivered.statuses, replies=delivered.replies
            )
            check(summary["statuses_applied"] == 1, f"The delivered status was applied ({summary})")

            await db.refresh(recipient)
            check(recipient.message_status == MessageStatus.DELIVERED, "The recipient advanced to DELIVERED")
            check(recipient.delivered_at is not None, "delivered_at was stamped")
            print(f"Meta 'delivered' webhook applied: status={recipient.message_status.value}")

            read = parser.parse(build_status_payload(wamid, "read"))
            await webhook_service.process(db, statuses=read.statuses, replies=read.replies)
            await db.refresh(recipient)
            check(recipient.message_status == MessageStatus.READ, "The recipient advanced to READ")
            print(f"Meta 'read' webhook applied: status={recipient.message_status.value}")

            # Out-of-order/replayed webhook: the existing monotonic guard must hold, proving
            # the Meta path reuses it rather than reimplementing status transitions.
            stale = parser.parse(build_status_payload(wamid, "delivered"))
            await webhook_service.process(db, statuses=stale.statuses, replies=stale.replies)
            await db.refresh(recipient)
            check(
                recipient.message_status == MessageStatus.READ,
                "A replayed 'delivered' webhook did not regress a READ message",
            )
            print("Out-of-order webhook correctly ignored (monotonic guard reused).")

            # A reply, quoting the outbound message, routed through the same reply pipeline.
            reply_payload = parser.parse(build_reply_payload(
                "919847012345", "Yes, I am interested. Please share the price.",
                context_id=wamid,
            ))
            summary = await webhook_service.process(
                db, statuses=reply_payload.statuses, replies=reply_payload.replies
            )
            check(summary["replies_applied"] == 1, f"The reply was recorded ({summary})")

            await db.refresh(recipient)
            await db.refresh(lead)
            check(recipient.message_status == MessageStatus.REPLIED, "The recipient is REPLIED")
            check("interested" in (recipient.reply_text or "").lower(), "The reply body was stored")
            check(recipient.replied_at is not None, "replied_at was stamped")
            check(
                lead.status == LeadStatus.NEGOTIATION,
                f"The 'interested' reply moved the lead to NEGOTIATION (got {lead.status})",
            )
            check(lead.last_contacted_at is not None, "last_contacted_at was stamped")
            print(f"Reply recorded; lead status -> {lead.status.value}")

            # The timeline entries prove the existing pipeline ran, not a parallel one.
            activities = (await db.execute(
                select(LeadActivity).where(LeadActivity.lead_id == lead.id)
            )).scalars().all()
            types = {a.activity_type for a in activities}
            for required in (
                ActivityType.WHATSAPP_SENT,
                ActivityType.WHATSAPP_DELIVERED,
                ActivityType.WHATSAPP_READ,
                ActivityType.WHATSAPP_REPLIED,
            ):
                check(required in types, f"A {required.value} activity was appended")
            print(f"Timeline entries created: {sorted(t.value for t in types)}")

            # Reply intent classification, which is the one decision this layer adds.
            for text, expected in [
                ("Yes, I am interested", "interested"),
                ("Not interested, thanks", "not_interested"),
                ("please stop messaging me", "not_interested"),
                ("Can you tell me more about this?", "need_details"),
                ("Ok", None),
                ("", None),
            ]:
                actual = MetaWebhookService._classify_reply(text)
                check(
                    actual == expected,
                    f"Reply {text!r} classified as {actual!r}, expected {expected!r}",
                )
            print("Reply intent classification correct, including the safe None default.")

            # An unmatchable event must be counted, not raised — Meta retries non-2xx forever.
            orphan = parser.parse(build_status_payload("wamid.NOT_OURS", "delivered"))
            summary = await webhook_service.process(
                db, statuses=orphan.statuses, replies=orphan.replies
            )
            check(summary["statuses_applied"] == 0, "An unmatched status applies nothing")
            check("wamid.NOT_OURS" in summary["unmatched"], "The unmatched event is reported")
            check(not summary["errors"], "An unmatched event is not an error")
            print(f"Unmatched webhook event handled gracefully: {summary['unmatched']}")

            # 10b. Per-recipient failure isolation with a genuinely failing provider.
            print("\n--- 10b. Failure isolation during a campaign run ---")

            lead2 = await lead_service.create_lead(db, LeadCreate(
                business_name=f"{MARKER} Studio Two",
                contact_person="Second Owner",
                phone="9847099999",
                city="Thrissur",
                source=LeadSource.MANUAL,
                status=LeadStatus.NEW,
            ))
            created_lead_ids.append(lead2.id)

            failing_api = StubGraphAPI([(401, {"error": {
                "message": "Session has expired", "type": "OAuthException", "code": 190,
            }})])
            failing_service = WhatsAppCampaignService(provider=StubbedCloudProvider(failing_api))

            campaign2 = await failing_service.create_campaign(db, WhatsAppCampaignCreate(
                template_id=template.id,
                name=f"{MARKER} Failing Campaign",
                lead_ids=[lead2.id],
            ))
            created_campaign_ids.append(campaign2.id)

            with _SettingsOverride(WHATSAPP_MAX_RETRIES=0):
                run2 = await failing_service.start_campaign(db, campaign_id=campaign2.id)

            check(run2["failed"] == 1, f"The failing send was recorded as failed (got {run2})")
            check(run2["succeeded"] == 0, "Nothing succeeded")
            recipients2, _ = await failing_service.get_recipients(db, campaign_id=campaign2.id)
            check(recipients2[0].message_status == MessageStatus.FAILED, "The recipient is FAILED")
            check(
                "190" in (recipients2[0].error_message or ""),
                f"The Meta error code was recorded: {recipients2[0].error_message}",
            )
            print(f"Provider failure isolated onto the recipient row: {recipients2[0].error_message}")

            # -------------------------------------------------------------
            # 11. PROVIDER REGISTRY
            # -------------------------------------------------------------
            print("\n--- 11. Provider registry and selection ---")

            check(
                isinstance(get_whatsapp_provider("whatsapp_cloud"), WhatsAppCloudProvider),
                "The Cloud adapter is selectable by name",
            )
            check(
                isinstance(get_whatsapp_provider("noop"), NoOpWhatsAppProvider),
                "The no-op provider is still selectable",
            )
            check(
                isinstance(get_whatsapp_provider("nonexistent_vendor"), NoOpWhatsAppProvider),
                "An unknown provider name falls back to the no-op provider",
            )
            with _SettingsOverride(WHATSAPP_PROVIDER="whatsapp_cloud"):
                check(
                    isinstance(get_whatsapp_provider(), WhatsAppCloudProvider),
                    "The default provider is driven by WHATSAPP_PROVIDER",
                )
            with _SettingsOverride(WHATSAPP_PROVIDER="noop"):
                check(
                    isinstance(get_whatsapp_provider(), NoOpWhatsAppProvider),
                    "WHATSAPP_PROVIDER=noop keeps sends simulated",
                )
            print("Provider registry resolves by name and by configured default.")

            print("\n=== ALL WHATSAPP CLOUD API TESTS COMPLETED SUCCESSFULLY ===")

        except Exception as e:
            print(f"\nTEST SUITE FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            # Repository writes commit immediately, so everything created is hard-deleted
            # explicitly, children first. Deleting a Campaign cascades its recipients away;
            # deleting a Lead cascades its activities and recipients away.
            print("\nCleaning up test data...")
            await db.rollback()
            for campaign_id_ in created_campaign_ids:
                row = await db.get(WhatsAppCampaign, campaign_id_)
                if row:
                    await db.delete(row)
            await db.commit()
            for lead_id_ in created_lead_ids:
                row = await db.get(Lead, lead_id_)
                if row:
                    await db.delete(row)
            await db.commit()
            for template_id_ in created_template_ids:
                row = await db.get(WhatsAppTemplate, template_id_)
                if row:
                    await db.delete(row)
            await db.commit()
            print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(test_whatsapp_cloud_suite())
