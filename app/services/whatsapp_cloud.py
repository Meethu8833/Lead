"""
app/services/whatsapp_cloud.py

This file implements `WhatsAppCloudProvider` — the production adapter that sends campaign
messages through Meta's WhatsApp Cloud API, plus `MetaWebhookVerifier` and
`MetaWebhookParser`, which handle the inbound half.

Under Clean Architecture this is an *adapter*: it implements the `WhatsAppProvider` port
defined in `app/services/whatsapp_provider.py` and it is the only module in the codebase
that knows what a Graph API URL looks like, what shape Meta's message JSON takes, or how
Meta signs a webhook. Nothing here imports a campaign service, a repository or a database
session, and no campaign business logic lives in this file — the campaign service keeps
calling the same four-argument `send_message` it always called.

Why templates, not free text
----------------------------
Meta permits free-form text to a user only inside a 24-hour "customer service window"
opened by that user messaging you first. A cold outreach campaign is by definition outside
that window, so a free-text send to a lead who has never written to us is rejected with
error 131047 — every recipient, every time. Business-initiated messaging must therefore go
out as a *pre-registered template*, identified by name and language, with positional
parameters.

That collides with the port's contract, which hands every adapter a fully-rendered string
(see the port's module docstring on why that is the only contract four vendors can share).
This adapter resolves the collision without changing the contract:

  * `WHATSAPP_USE_TEMPLATES=true` (the default) sends the CRM template's **name** and
    **language** — both of which the port already passes through — as a Meta template, with
    the rendered body supplied as a single positional parameter when the registered
    template declares one.
  * `WHATSAPP_USE_TEMPLATES=false` sends the rendered string as free text, which is correct
    for replying inside an open service window.

The CRM template's `name` must therefore match a template registered and approved in the
Meta Business Manager. That coupling is real and unavoidable — it is Meta's model, not a
design choice here — and it is documented in walkthrough.md as an operational requirement.

The failure contract, and why it is the whole point
---------------------------------------------------
The port's contract is that an adapter never raises for a per-message rejection. That is
load-bearing here in a way it was not for the no-op provider, because a real network is
involved. Every failure mode named in the specification is mapped to a
`ProviderSendResult(success=False, ...)` and never to an exception:

  * **429 rate limit** — retried with backoff honouring Meta's `Retry-After`, then returned
    as a retryable failure.
  * **Expired / invalid access token** (Meta codes 190, 102, 401) — returned as a
    *non*-retryable failure, and *not* retried: an expired token will still be expired in
    two seconds, and retrying it 5,000 times turns a configuration error into an outage.
  * **Invalid template** (132000-132100, 131047) — non-retryable; the template needs fixing
    in Business Manager, not resending.
  * **Network timeout / connection error** — retried, then returned as retryable.
  * **Provider unavailable** (5xx) — retried, then returned as retryable.

`send_message` has a blanket `except Exception` as its last line of defence. That is
deliberate and is not a swallowed bug: the campaign loop dispatches thousands of recipients
and an unforeseen fault on recipient 400 must cost that one recipient, not the other 4,600.
The exception is logged with a traceback before being converted.

Configuration
-------------
Every credential and knob is read from `app/core/config.py`, which reads the environment.
No token, URL, or secret is hardcoded, and `validate_configuration()` reports exactly which
variables are unset without making a network call.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.services.whatsapp_provider import (
    ProviderConfigurationResult,
    ProviderMessageStatus,
    ProviderSendResult,
    WhatsAppProvider,
    register_whatsapp_provider,
)

logger = logging.getLogger(__name__)


# =====================================================================
# ERROR CLASSIFICATION
# =====================================================================

#: Meta error codes that mean the caller's credentials are the problem. These are never
#: retried: an expired token is still expired one second later, and retrying it once per
#: recipient converts a five-minute credential rotation into a campaign-wide failure storm
#: against Meta's rate limiter.
_AUTH_ERROR_CODES = frozenset({0, 102, 190, 200, 10, 2500})

#: Meta error codes that mean the *template* is wrong — missing, unapproved, wrong language,
#: or a parameter count that does not match what was registered. Also never retried: no
#: amount of resending fixes a template that does not exist. 131047 ("re-engagement
#: message") lands here too, since it means a free-text send was attempted outside the
#: 24-hour window and the fix is to send a template instead.
_TEMPLATE_ERROR_CODES = frozenset({131047, 132000, 132001, 132005, 132007, 132012, 132015, 132016, 132068, 132069})

#: Meta error codes that mean "slow down". Retried with backoff.
_RATE_LIMIT_ERROR_CODES = frozenset({4, 80007, 130429, 131048, 131056})

#: Meta error codes describing a bad *recipient* — not a WhatsApp user, invalid number.
#: Permanent for that recipient and irrelevant to every other one, so: not retried, and the
#: reason is written onto that recipient's row.
_RECIPIENT_ERROR_CODES = frozenset({131026, 131021, 131052, 133010})

#: HTTP statuses worth retrying regardless of what Meta's body says. 408/504 are timeouts,
#: 429 is the rate limiter, 5xx is Meta being unwell.
_RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class _GraphError:
    """
    One decoded error from a Graph API response, classified for the retry decision.

    Separated from the send path so the classification is a pure function of the response
    and can be tested without a network — which is exactly what the specification's
    "provider failures" test requires.
    """
    message: str
    code: int | None = None
    subcode: int | None = None
    http_status: int | None = None
    retryable: bool = False
    #: A short machine-readable category, recorded on the result so a future
    #: "retry failed recipients" action can filter without parsing English.
    category: str = "unknown"

    def as_text(self) -> str:
        """
        Renders the error for storage in `CampaignRecipient.error_message`, which is what an
        operator actually reads when a send fails. The code is included because Meta's
        documentation is indexed by code, not by message text.
        """
        parts = [self.message or "The provider rejected the message."]
        if self.code is not None:
            parts.append(f"(Meta error {self.code}" + (f"/{self.subcode}" if self.subcode else "") + ")")
        elif self.http_status is not None:
            parts.append(f"(HTTP {self.http_status})")
        return " ".join(parts)


def classify_graph_error(
    payload: dict[str, Any] | None,
    http_status: int | None = None,
    fallback_message: str | None = None,
) -> _GraphError:
    """
    Turns a Graph API error response into a classified `_GraphError`.

    Pure and offline. The classification order matters: a code-based verdict beats an
    HTTP-status-based one, because Meta returns 400 for both "your token expired" (never
    retry) and "you are being rate limited" (do retry), and only the code tells them apart.
    An unrecognised code falls back to the HTTP status, and an unrecognised status is
    treated as non-retryable — the conservative default, since retrying an error we do not
    understand risks duplicating a message that may in fact have been sent.
    """
    error = _as_dict(_as_dict(payload).get("error"))
    message = error.get("message") or fallback_message or "The provider rejected the message."
    code = error.get("code")
    subcode = error.get("error_subcode")

    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    try:
        subcode = int(subcode) if subcode is not None else None
    except (TypeError, ValueError):
        subcode = None

    # Meta nests the useful human explanation one level down more often than not.
    detail = _as_dict(error.get("error_data")).get("details")
    if detail and detail not in message:
        message = f"{message}: {detail}"

    if code in _AUTH_ERROR_CODES:
        return _GraphError(
            message=message, code=code, subcode=subcode, http_status=http_status,
            retryable=False, category="auth",
        )
    if code in _TEMPLATE_ERROR_CODES:
        return _GraphError(
            message=message, code=code, subcode=subcode, http_status=http_status,
            retryable=False, category="template",
        )
    if code in _RECIPIENT_ERROR_CODES:
        return _GraphError(
            message=message, code=code, subcode=subcode, http_status=http_status,
            retryable=False, category="recipient",
        )
    if code in _RATE_LIMIT_ERROR_CODES or http_status == 429:
        return _GraphError(
            message=message, code=code, subcode=subcode, http_status=http_status,
            retryable=True, category="rate_limit",
        )
    if http_status in _RETRYABLE_HTTP_STATUSES:
        return _GraphError(
            message=message, code=code, subcode=subcode, http_status=http_status,
            retryable=True, category="unavailable",
        )
    if http_status == 401 or http_status == 403:
        return _GraphError(
            message=message, code=code, subcode=subcode, http_status=http_status,
            retryable=False, category="auth",
        )
    return _GraphError(
        message=message, code=code, subcode=subcode, http_status=http_status,
        retryable=False, category="unknown",
    )


# =====================================================================
# PHONE NORMALISATION
# =====================================================================

#: Anything that is not a digit. Meta wants E.164 *without* the leading '+', so the safest
#: normalisation is "strip everything that is not a digit, then reason about the result".
_NON_DIGITS = re.compile(r"\D+")


def normalize_msisdn(phone: str, default_country_code: str | None = None) -> str | None:
    """
    Normalises a stored phone number into the digits-only E.164 form Meta requires.

    Returns None when the input cannot be made into a plausible number, so the caller can
    fail that one recipient with a clear reason instead of sending Meta something it will
    reject.

    The country-code rule is the part that matters in practice. The CRM's leads are Indian
    and are routinely stored as bare 10-digit numbers ("9847012345"), sometimes with a
    national trunk prefix ("09847012345"), sometimes fully qualified ("+91 98470 12345").
    All three must reach Meta as "919847012345":

      * a leading '+' means the number is already fully qualified — trust it,
      * a single leading '0' is a national trunk prefix — drop it, then prepend the code,
      * a number already starting with the configured country code and long enough to be
        complete is left alone,
      * anything else short enough to be a national number gets the code prepended.

    A number that is already 11-15 digits and does *not* start with the configured code is
    left untouched: it is most likely a foreign number that is already qualified, and
    prepending '91' to it would silently misroute the message.
    """
    if not phone:
        return None

    raw = phone.strip()
    had_plus = raw.startswith("+")
    digits = _NON_DIGITS.sub("", raw)

    if not digits:
        return None

    code = _NON_DIGITS.sub("", default_country_code or settings.WHATSAPP_DEFAULT_COUNTRY_CODE or "")

    if had_plus:
        # Explicitly qualified by the operator; nothing to infer.
        return digits if 7 <= len(digits) <= 15 else None

    # A national trunk prefix ('0' before the subscriber number) is never part of E.164.
    if digits.startswith("0"):
        digits = digits.lstrip("0")
        if not digits:
            return None

    if code and digits.startswith(code) and len(digits) > len(code) + 6:
        # Already carries the country code.
        pass
    elif code and len(digits) <= 11:
        # A national-length number: qualify it.
        digits = f"{code}{digits}"

    if not 7 <= len(digits) <= 15:
        return None
    return digits


# =====================================================================
# THE PROVIDER
# =====================================================================

@register_whatsapp_provider
class WhatsAppCloudProvider(WhatsAppProvider):
    """
    Adapter that sends campaign messages through Meta's WhatsApp Cloud API.

    One instance is constructed per campaign run and reused across every recipient, per the
    port's contract. It holds no per-message state, so it is safe to share; the HTTP client
    is opened per request rather than held on the instance, because the instance may outlive
    the event loop it was created on (the campaign service caches it on the service object,
    which FastAPI may reuse across requests).
    """

    name = "whatsapp_cloud"

    def __init__(
        self,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        business_account_id: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
    ) -> None:
        """
        Args:
            access_token / phone_number_id / business_account_id / base_url / api_version:
                Explicit overrides for the configured values. These exist so a test can
                drive the adapter against a stub transport; production construction (via
                the registry, which takes no arguments) always reads settings.
        """
        self._access_token = (
            access_token if access_token is not None else settings.WHATSAPP_ACCESS_TOKEN
        )
        self._phone_number_id = (
            phone_number_id if phone_number_id is not None else settings.WHATSAPP_PHONE_NUMBER_ID
        )
        self._business_account_id = (
            business_account_id if business_account_id is not None
            else settings.WHATSAPP_BUSINESS_ACCOUNT_ID
        )
        self._base_url = (base_url or settings.WHATSAPP_GRAPH_BASE_URL).rstrip("/")
        self._api_version = (api_version or settings.GRAPH_API_VERSION).strip("/")

    @staticmethod
    def _import_httpx() -> Any | None:
        """
        Imports `httpx` lazily, returning None when it is absent.

        Deferred for the same reason the Google Maps provider defers it: this module is
        imported by the provider registry at resolution time, and a top-level import would
        take the API down on a deployment that never uses this adapter. Returning None
        rather than raising lets `_dispatch` convert an absent dependency into an ordinary
        per-message failure, keeping the port's no-raise contract intact.

        A method rather than a module function specifically so a test can subclass this
        adapter, override this one hook, and drive every real code path — payload
        construction, retry loop, error classification — against a stub transport. That is
        the same seam `GoogleMapsLeadProvider` and `InstagramLeadProvider` expose.
        """
        try:
            import httpx  # noqa: PLC0415 - deferred on purpose, see docstring
        except ImportError:  # pragma: no cover - depends on the deployment image
            logger.error(
                "The 'httpx' package is not installed, so the WhatsApp Cloud API adapter "
                "cannot send. Install it with: pip install httpx"
            )
            return None
        return httpx

    # -----------------------------------------------------------------
    # CONFIGURATION
    # -----------------------------------------------------------------

    @property
    def messages_url(self) -> str:
        """The Cloud API endpoint this adapter POSTs messages to."""
        return f"{self._base_url}/{self._api_version}/{self._phone_number_id}/messages"

    @property
    def is_configured(self) -> bool:
        """
        Whether the two credentials a *send* actually needs are present. The business
        account id and verify token are not checked here because neither is required to
        send — demanding them would refuse sends on a deployment that is perfectly able to
        make them.
        """
        return bool((self._access_token or "").strip() and (self._phone_number_id or "").strip())

    async def validate_configuration(self) -> ProviderConfigurationResult:
        """
        Reports which credentials are missing, without any network I/O.

        Send-critical credentials go in `missing` and make the result invalid. Credentials
        that only disable a *part* of the integration — the WABA id (template catalogue),
        the verify token (webhook handshake), the app secret (signature verification) — are
        reported as warnings instead, because a deployment that only sends outbound messages
        and never receives webhooks is a legitimate configuration and should not be reported
        as broken.

        The app-secret warning is phrased as a security warning specifically: without it,
        signature verification cannot run, and a webhook that cannot verify signatures is
        one anyone on the internet can call.
        """
        missing: list[str] = []
        warnings: list[str] = []

        if not (self._access_token or "").strip():
            missing.append("WHATSAPP_ACCESS_TOKEN")
        if not (self._phone_number_id or "").strip():
            missing.append("WHATSAPP_PHONE_NUMBER_ID")

        if not (self._business_account_id or "").strip():
            warnings.append(
                "WHATSAPP_BUSINESS_ACCOUNT_ID is unset; the template catalogue cannot be read"
            )
        if not (settings.WHATSAPP_VERIFY_TOKEN or "").strip():
            warnings.append(
                "WHATSAPP_VERIFY_TOKEN is unset; Meta's webhook subscription handshake will fail"
            )
        if not (settings.WHATSAPP_APP_SECRET or "").strip():
            warnings.append(
                "WHATSAPP_APP_SECRET is unset; inbound webhook signatures cannot be verified"
            )
        if not settings.WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE:
            warnings.append(
                "WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE is disabled; unsigned webhooks are accepted "
                "(never do this in production)"
            )

        valid = not missing
        return ProviderConfigurationResult(
            valid=valid,
            provider=self.name,
            missing=missing,
            warnings=warnings,
            detail=(
                f"Sending as phone number id '{self._phone_number_id}' via "
                f"{self._api_version}."
                if valid else
                "Set the missing variables in the environment to enable this provider."
            ),
        )

    # -----------------------------------------------------------------
    # SENDING
    # -----------------------------------------------------------------

    async def send_message(
        self,
        phone: str,
        message: str,
        *,
        template_name: str | None = None,
        language: str = "en",
    ) -> ProviderSendResult:
        """
        Sends one message to one number — the method the campaign service calls.

        Routes to a template send or a free-text send according to
        `WHATSAPP_USE_TEMPLATES` and whether a template name was supplied. Business-initiated
        campaign messaging needs a template (see the module docstring), so the template path
        is the default; the free-text path exists for replying inside an open 24-hour
        service window.

        Never raises. Every failure — misconfiguration, an unusable number, a rejection from
        Meta, a timeout, an unforeseen bug in this adapter — comes back as
        `ProviderSendResult(success=False, ...)` so the campaign run marks that one recipient
        FAILED and continues.
        """
        try:
            if settings.WHATSAPP_USE_TEMPLATES and template_name:
                return await self.send_template(
                    phone,
                    template_name,
                    language=language,
                    parameters=[message] if message else None,
                    fallback_text=message,
                )
            return await self._send_text(phone, message)
        except Exception as exc:  # noqa: BLE001 - the port forbids raising; see module docstring
            logger.exception(
                "WhatsAppCloudProvider: unexpected error sending to %s", _redact_phone(phone)
            )
            return ProviderSendResult(
                success=False,
                error=f"Provider error: {exc}",
                provider=self.name,
                retryable=True,
                error_code="adapter_exception",
            )

    async def send_template(
        self,
        phone: str,
        template_name: str,
        *,
        language: str = "en",
        parameters: list[str] | None = None,
        header_parameters: list[str] | None = None,
        fallback_text: str | None = None,
    ) -> ProviderSendResult:
        """
        Sends a pre-registered Meta template by name, with positional body parameters.

        The `components` array is built only for the parameters actually supplied. A
        registered template with no placeholders must be sent with *no* body component at
        all — sending an empty one is rejected with error 132000 — which is why the list is
        assembled conditionally rather than always including a body entry.

        Meta matches templates by (name, language) pair, and its language codes are
        underscore-separated locales ("en_US", "pt_BR") while the CRM stores BCP-47-ish
        codes that may use a hyphen. `_normalize_language` bridges the two so a template
        registered as "en_US" is still found when the CRM template says "en-US".
        """
        if not self.is_configured:
            return self._misconfigured_result()

        destination = normalize_msisdn(phone)
        if destination is None:
            return ProviderSendResult(
                success=False,
                error=f"'{phone}' is not a usable WhatsApp number.",
                provider=self.name,
                retryable=False,
                error_code="invalid_number",
            )

        components: list[dict[str, Any]] = []
        if header_parameters:
            components.append({
                "type": "header",
                "parameters": [{"type": "text", "text": str(value)} for value in header_parameters],
            })
        if parameters:
            components.append({
                "type": "body",
                "parameters": [{"type": "text", "text": str(value)} for value in parameters],
            })

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destination,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": _normalize_language(language)},
            },
        }
        if components:
            payload["template"]["components"] = components

        return await self._dispatch(payload, destination)

    async def _send_text(self, phone: str, message: str) -> ProviderSendResult:
        """
        Sends a free-text message, valid only inside an open 24-hour service window.

        `preview_url` is set to False deliberately: link previews cause Meta to fetch the
        URL server-side, which both slows the send and leaks the fact that a campaign is
        running to whatever is on the other end of the link.
        """
        if not self.is_configured:
            return self._misconfigured_result()

        if not (message or "").strip():
            return ProviderSendResult(
                success=False,
                error="Refusing to send an empty message body.",
                provider=self.name,
                retryable=False,
                error_code="empty_message",
            )

        destination = normalize_msisdn(phone)
        if destination is None:
            return ProviderSendResult(
                success=False,
                error=f"'{phone}' is not a usable WhatsApp number.",
                provider=self.name,
                retryable=False,
                error_code="invalid_number",
            )

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destination,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }
        return await self._dispatch(payload, destination)

    def _misconfigured_result(self) -> ProviderSendResult:
        """
        The result returned for every send when credentials are absent.

        Non-retryable on purpose: a missing token is a deployment problem, and retrying it
        per recipient would turn one clear error into thousands of identical ones.
        """
        missing = [
            var for var, value in (
                ("WHATSAPP_ACCESS_TOKEN", self._access_token),
                ("WHATSAPP_PHONE_NUMBER_ID", self._phone_number_id),
            ) if not (value or "").strip()
        ]
        return ProviderSendResult(
            success=False,
            error=(
                "WhatsApp Cloud API is not configured: "
                f"{', '.join(missing)} {'are' if len(missing) != 1 else 'is'} unset."
            ),
            provider=self.name,
            retryable=False,
            error_code="not_configured",
        )

    # -----------------------------------------------------------------
    # TRANSPORT
    # -----------------------------------------------------------------

    async def _dispatch(self, payload: dict[str, Any], destination: str) -> ProviderSendResult:
        """
        POSTs one message payload to the Cloud API, with bounded retries, and converts the
        outcome into a `ProviderSendResult`.

        Retries only what is worth retrying (see `classify_graph_error`) and stops at
        `WHATSAPP_MAX_RETRIES`. Between attempts it honours Meta's `Retry-After` header when
        present, falling back to exponential backoff — Meta knows how long its own rate
        limiter needs better than a fixed constant does.

        The retry loop lives here rather than around `send_message` so that a retry never
        re-runs template rendering or number normalisation, both of which are deterministic
        and would just burn CPU per attempt.
        """
        httpx = self._import_httpx()
        if httpx is None:
            return ProviderSendResult(
                success=False,
                error=(
                    "The 'httpx' package is required for WhatsApp Cloud API sending but is "
                    "not installed. Install it with: pip install httpx"
                ),
                provider=self.name,
                retryable=False,
                error_code="missing_dependency",
            )

        attempts = max(0, settings.WHATSAPP_MAX_RETRIES) + 1
        last: _GraphError | None = None

        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(_backoff_delay(attempt, last))

            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(settings.WHATSAPP_TIMEOUT_SECONDS)
                ) as client:
                    response = await client.post(
                        self.messages_url,
                        headers={
                            "Authorization": f"Bearer {self._access_token}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
            except Exception as exc:  # noqa: BLE001 - any transport fault, incl. timeouts
                # A timeout or connection reset is retryable: the request may never have
                # reached Meta. Note the duplicate-send risk this accepts — see the
                # walkthrough; Meta does not offer an idempotency key on this endpoint.
                last = _GraphError(
                    message=f"Could not reach the WhatsApp Cloud API: {exc}",
                    retryable=True,
                    category="network",
                )
                logger.warning(
                    "WhatsApp Cloud API request failed (attempt %d/%d) for %s: %s",
                    attempt + 1, attempts, _redact_phone(destination), exc,
                )
                continue

            body = _decode_json(response)

            if response.status_code < 400:
                message_id = _first_message_id(body)
                if not message_id:
                    # A 2xx with no message id is not something to retry — Meta accepted
                    # something, and resending risks a duplicate. Surface it as a failure so
                    # the recipient row records that we cannot track this message.
                    last = _GraphError(
                        message="The provider accepted the message but returned no message id.",
                        http_status=response.status_code,
                        retryable=False,
                        category="unknown",
                    )
                    break
                logger.info(
                    "WhatsApp Cloud API: accepted message to %s -> %s",
                    _redact_phone(destination), message_id,
                )
                return ProviderSendResult(
                    success=True,
                    message_id=message_id,
                    provider=self.name,
                )

            last = classify_graph_error(
                body,
                http_status=response.status_code,
                fallback_message=f"The provider returned HTTP {response.status_code}.",
            )
            logger.warning(
                "WhatsApp Cloud API rejected a message to %s (attempt %d/%d): %s [%s]",
                _redact_phone(destination), attempt + 1, attempts, last.as_text(), last.category,
            )

            # A retry header on a non-retryable error changes nothing; classification wins.
            if not last.retryable:
                break
            last = _with_retry_after(last, response)

        error = last or _GraphError(message="The provider rejected the message.")
        return ProviderSendResult(
            success=False,
            error=error.as_text(),
            provider=self.name,
            retryable=error.retryable,
            error_code=str(error.code) if error.code is not None else error.category,
        )

    # -----------------------------------------------------------------
    # STATUS
    # -----------------------------------------------------------------

    async def get_message_status(self, message_id: str) -> ProviderMessageStatus | None:
        """
        Attempts to read one message's delivery state back from Meta.

        Meta's Cloud API has **no** endpoint that returns a sent message's delivery state:
        status is push-only, delivered through webhooks. This method therefore returns None
        — the port's documented "this vendor cannot be polled" answer — rather than
        pretending to poll or issuing a call that always 404s.

        It is implemented rather than left inherited so that this fact is stated at the
        point someone will look for it, instead of being an invisible inherited default that
        reads like an oversight. Reconciling a missed webhook means re-requesting it in the
        Meta app dashboard, not asking the API.
        """
        logger.debug(
            "WhatsAppCloudProvider.get_message_status(%s): the Cloud API does not expose "
            "message status reads; delivery state arrives by webhook only.",
            message_id,
        )
        return None

    async def health_check(self) -> bool:
        """
        Reports whether the adapter can reach Meta with its configured credentials.

        Reads the sender's own phone-number node, which is the cheapest authenticated GET
        available and touches no message quota. A False here lets a campaign fail fast
        instead of marking every recipient FAILED one at a time.
        """
        if not self.is_configured:
            return False

        httpx = self._import_httpx()
        if httpx is None:
            return False

        url = f"{self._base_url}/{self._api_version}/{self._phone_number_id}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(settings.WHATSAPP_TIMEOUT_SECONDS)
            ) as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    params={"fields": "id,verified_name,quality_rating"},
                )
        except Exception as exc:  # noqa: BLE001 - unreachable is simply unhealthy
            logger.warning("WhatsApp Cloud API health check failed: %s", exc)
            return False

        if response.status_code >= 400:
            logger.warning(
                "WhatsApp Cloud API health check returned HTTP %d: %s",
                response.status_code, classify_graph_error(_decode_json(response)).as_text(),
            )
            return False
        return True


# =====================================================================
# WEBHOOK VERIFICATION
# =====================================================================

class MetaWebhookVerifier:
    """
    Verifies that an inbound webhook request genuinely came from Meta.

    Two separate mechanisms, for the two separate request types Meta makes:

    - **GET (subscription handshake)** — Meta calls the endpoint once with `hub.mode`,
      `hub.verify_token` and `hub.challenge` when an operator subscribes the webhook in the
      app dashboard. The endpoint must echo `hub.challenge` back as plain text, and only if
      the token matches the configured one.
    - **POST (event delivery)** — every event payload carries an `X-Hub-Signature-256`
      header holding `sha256=<hex>`, an HMAC of the **raw request body** keyed by the Meta
      *app secret*. Verification must run against the exact bytes received, which is why the
      endpoint reads `await request.body()` and parses the JSON itself rather than letting
      FastAPI deserialise it — re-serialising a parsed body produces different bytes and the
      signature would never match.

    Both comparisons use `hmac.compare_digest` rather than `==`, so a timing side channel
    cannot be used to recover the token or forge a signature byte by byte.
    """

    def __init__(self, verify_token: str | None = None, app_secret: str | None = None) -> None:
        self._verify_token = (
            verify_token if verify_token is not None else settings.WHATSAPP_VERIFY_TOKEN
        )
        self._app_secret = (
            app_secret if app_secret is not None else settings.WHATSAPP_APP_SECRET
        )

    def verify_challenge(
        self, mode: str | None, token: str | None, challenge: str | None
    ) -> str | None:
        """
        Validates Meta's GET subscription handshake and returns the challenge to echo.

        Returns None when the handshake must be rejected — wrong mode, wrong token, or no
        verify token configured on our side. An unconfigured verify token deliberately fails
        *closed*: accepting any token when none is configured would let anyone subscribe a
        webhook to this endpoint.
        """
        if not (self._verify_token or "").strip():
            logger.error(
                "Rejecting a webhook verification handshake: WHATSAPP_VERIFY_TOKEN is unset."
            )
            return None
        if mode != "subscribe":
            logger.warning("Rejecting a webhook handshake with hub.mode=%r.", mode)
            return None
        if not token or not hmac.compare_digest(token, self._verify_token):
            logger.warning("Rejecting a webhook handshake: hub.verify_token did not match.")
            return None
        if challenge is None:
            logger.warning("Rejecting a webhook handshake: no hub.challenge was supplied.")
            return None
        return challenge

    def verify_signature(self, raw_body: bytes, signature_header: str | None) -> bool:
        """
        Verifies the `X-Hub-Signature-256` HMAC over the raw request body.

        Returns False for a missing header, a malformed one, or a mismatch. When
        `WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE` is disabled the check is skipped and True is
        returned with a loud warning — that switch exists so a developer can replay a
        captured payload with curl, and it must never be on in production.

        A missing app secret fails *closed* (when verification is required), for the same
        reason the verify token does: an endpoint that cannot check signatures and accepts
        anyway is an unauthenticated write path into lead statuses.
        """
        if not settings.WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE:
            logger.warning(
                "Accepting a WhatsApp webhook WITHOUT signature verification because "
                "WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE is disabled."
            )
            return True

        if not (self._app_secret or "").strip():
            logger.error(
                "Rejecting a WhatsApp webhook: WHATSAPP_APP_SECRET is unset, so its "
                "signature cannot be verified."
            )
            return False

        if not signature_header:
            logger.warning("Rejecting a WhatsApp webhook: no X-Hub-Signature-256 header.")
            return False

        prefix, _, supplied = signature_header.partition("=")
        if prefix.strip().lower() != "sha256" or not supplied:
            logger.warning(
                "Rejecting a WhatsApp webhook: malformed signature header %r.", signature_header
            )
            return False

        expected = hmac.new(
            self._app_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected, supplied.strip().lower()):
            logger.warning("Rejecting a WhatsApp webhook: signature mismatch.")
            return False
        return True

    def sign(self, raw_body: bytes) -> str:
        """
        Produces the header value Meta would send for this body.

        Exists for tests, which must be able to sign a payload the way Meta does in order to
        exercise the accept path without a real Meta app. Keeping it here rather than
        duplicating the HMAC in the test suite means the test verifies the real algorithm
        rather than its own copy of it.
        """
        digest = hmac.new(
            (self._app_secret or "").encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        return f"sha256={digest}"


# =====================================================================
# WEBHOOK PAYLOAD PARSING
# =====================================================================

#: Meta's delivery status strings, mapped onto the CRM's `MessageStatus` *names*. Deliberately
#: mapped to plain strings rather than to the enum: this module must not import the campaign
#: domain model (the port's whole point is that the domain does not depend on a vendor, and
#: the reverse dependency would be just as wrong). The endpoint resolves the name to the enum.
#:
#: Meta emits four statuses. 'accepted' and 'sent' both mean "Meta has it"; 'deleted' is a
#: user deleting the message on their device, which is not a delivery outcome and is ignored.
META_STATUS_TO_MESSAGE_STATUS: dict[str, str] = {
    "accepted": "SENT",
    "sent": "SENT",
    "delivered": "DELIVERED",
    "read": "READ",
    "failed": "FAILED",
}


@dataclass(frozen=True)
class InboundStatusEvent:
    """One delivery-status event extracted from a Meta webhook payload."""
    provider_message_id: str
    #: The CRM `MessageStatus` *name* this maps to (e.g. "DELIVERED").
    status: str
    occurred_at: datetime | None = None
    error_message: str | None = None
    recipient_phone: str | None = None


@dataclass(frozen=True)
class InboundReplyEvent:
    """One inbound message (a lead's reply) extracted from a Meta webhook payload."""
    from_phone: str
    text: str
    provider_message_id: str | None = None
    #: The id of *our* outbound message this reply quotes, when the lead used WhatsApp's
    #: reply-to feature. This is the only way Meta lets us pin a reply to an exact outbound
    #: message; without it the campaign service falls back to matching on phone number.
    context_message_id: str | None = None
    occurred_at: datetime | None = None
    message_type: str = "text"


@dataclass
class ParsedWebhook:
    """
    Everything actionable extracted from one Meta webhook POST.

    Statuses and replies are kept separate because they drive two different services with
    two different risk profiles — `WhatsAppCampaignService.apply_delivery_status` and
    `CampaignReplyService.record_reply` — and one payload legitimately contains both.
    """
    statuses: list[InboundStatusEvent] = field(default_factory=list)
    replies: list[InboundReplyEvent] = field(default_factory=list)
    #: Entries the parser understood the shape of but chose not to act on (a reaction, a
    #: 'deleted' status, an unsupported message type), recorded so the endpoint can log why
    #: a webhook produced no effect instead of looking silently broken.
    ignored: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.statuses and not self.replies


class MetaWebhookParser:
    """
    Translates Meta's webhook JSON into the flat event objects the campaign services need.

    Meta's payload is deeply nested and batched — `entry[] -> changes[] -> value ->
    {statuses[], messages[]}` — and one POST may carry status updates for several messages
    and inbound replies from several people at once. Everything in this class is a pure
    function of the payload: no I/O, no database, no domain imports. That is what makes the
    parsing testable against captured real payloads, which is exactly how the test suite
    exercises it.

    The parser is defensive to the point of paranoia about shape. Meta adds fields and event
    types without warning, and a webhook that raises is a webhook Meta retries — repeatedly
    — so an unrecognised entry is recorded in `ignored` and skipped, never allowed to
    propagate an exception.
    """

    def parse(self, payload: dict[str, Any]) -> ParsedWebhook:
        """
        Extracts every status update and inbound reply from one webhook body.

        Non-WhatsApp payloads (Meta delivers other products' events to the same endpoint if
        an app is subscribed to them) are skipped by the `object` check rather than
        misparsed.
        """
        result = ParsedWebhook()

        if not isinstance(payload, dict):
            result.ignored.append("Payload was not a JSON object.")
            return result

        obj = payload.get("object")
        if obj and obj != "whatsapp_business_account":
            result.ignored.append(f"Ignored a webhook for object '{obj}'.")
            return result

        # Every level is type-checked rather than merely null-checked. `x or {}` guards None
        # but not a string or a number, and a webhook that raises is one Meta retries with
        # escalating backoff until it disables the subscription — so a malformed entry must
        # be skipped, never propagated.
        for entry in _as_list(payload.get("entry")):
            if not isinstance(entry, dict):
                result.ignored.append("Ignored a malformed entry.")
                continue

            for change in _as_list(entry.get("changes")):
                if not isinstance(change, dict):
                    result.ignored.append("Ignored a malformed change entry.")
                    continue

                value = change.get("value")
                if not isinstance(value, dict):
                    continue

                for raw_status in _as_list(value.get("statuses")):
                    event = self._parse_status(raw_status, result)
                    if event:
                        result.statuses.append(event)

                for raw_message in _as_list(value.get("messages")):
                    event = self._parse_message(raw_message, result)
                    if event:
                        result.replies.append(event)

        return result

    def _parse_status(
        self, raw: Any, result: ParsedWebhook
    ) -> InboundStatusEvent | None:
        """
        Maps one entry of Meta's `statuses[]` onto an `InboundStatusEvent`.

        A failed status carries its reason in an `errors[]` array; the first entry's title
        and message are joined into one line for `CampaignRecipient.error_message`, because
        that column is what an operator reads when they ask why a lead never got the
        message.
        """
        if not isinstance(raw, dict):
            result.ignored.append("Ignored a malformed status entry.")
            return None

        message_id = raw.get("id")
        meta_status = (raw.get("status") or "").strip().lower()

        if not message_id:
            result.ignored.append("Ignored a status entry with no message id.")
            return None

        mapped = META_STATUS_TO_MESSAGE_STATUS.get(meta_status)
        if not mapped:
            # 'deleted' and anything Meta adds later land here.
            result.ignored.append(f"Ignored status '{meta_status}' for message {message_id}.")
            return None

        error_message = None
        errors = _as_list(raw.get("errors"))
        if errors and isinstance(errors[0], dict):
            first = errors[0]
            title = first.get("title") or first.get("message") or "Delivery failed."
            detail = _as_dict(first.get("error_data")).get("details")
            code = first.get("code")
            error_message = title if not detail else f"{title}: {detail}"
            if code is not None:
                error_message = f"{error_message} (Meta error {code})"

        return InboundStatusEvent(
            provider_message_id=str(message_id),
            status=mapped,
            occurred_at=_parse_epoch(raw.get("timestamp")),
            error_message=error_message,
            recipient_phone=raw.get("recipient_id"),
        )

    def _parse_message(
        self, raw: Any, result: ParsedWebhook
    ) -> InboundReplyEvent | None:
        """
        Maps one entry of Meta's `messages[]` onto an `InboundReplyEvent`.

        Text bodies, interactive button/list replies and button taps are all treated as
        replies with usable text, because from the CRM's point of view a lead tapping
        "Interested" is a reply that should move their status exactly as typing "interested"
        would. Media and reactions produce a placeholder text instead of being dropped: a
        lead who answers a campaign with a voice note has *replied*, and recording that with
        "[audio message]" is far more useful than the timeline showing nothing happened.
        """
        if not isinstance(raw, dict):
            result.ignored.append("Ignored a malformed message entry.")
            return None

        sender = raw.get("from")
        if not sender:
            result.ignored.append("Ignored an inbound message with no sender.")
            return None

        message_type = (raw.get("type") or "").strip().lower()
        text = _extract_message_text(raw, message_type)

        if text is None:
            result.ignored.append(
                f"Ignored an inbound '{message_type or 'unknown'}' message from a lead."
            )
            return None

        return InboundReplyEvent(
            from_phone=str(sender),
            text=text,
            provider_message_id=raw.get("id"),
            context_message_id=_as_dict(raw.get("context")).get("id"),
            occurred_at=_parse_epoch(raw.get("timestamp")),
            message_type=message_type or "text",
        )


def _extract_message_text(raw: dict[str, Any], message_type: str) -> str | None:
    """
    Pulls readable text out of any inbound message type Meta might deliver.

    Returns None only for message types that carry no lead intent at all (a reaction, a
    system notification), which the caller records as ignored. Everything a human
    deliberately sent produces text, even if that text is a placeholder describing the
    media — see `_parse_message` for why.
    """
    if message_type == "text":
        body = _as_dict(raw.get("text")).get("body")
        return body if body else None

    if message_type == "button":
        # A tap on a template's quick-reply button.
        button = _as_dict(raw.get("button"))
        return button.get("text") or button.get("payload") or None

    if message_type == "interactive":
        interactive = _as_dict(raw.get("interactive"))
        for key in ("button_reply", "list_reply"):
            reply = _as_dict(interactive.get(key))
            title = reply.get("title") or reply.get("id")
            if title:
                return str(title)
        return None

    if message_type in {"image", "video", "audio", "document", "sticker", "voice"}:
        caption = _as_dict(raw.get(message_type)).get("caption")
        return caption or f"[{message_type} message]"

    if message_type == "location":
        location = _as_dict(raw.get("location"))
        name = location.get("name") or location.get("address")
        return f"[location: {name}]" if name else "[location shared]"

    if message_type == "contacts":
        return "[contact card shared]"

    # Reactions, system messages, order messages and anything Meta adds later: no lead
    # intent worth recording as a reply.
    return None


# =====================================================================
# INTERNAL HELPERS
# =====================================================================

def _decode_json(response: Any) -> dict[str, Any]:
    """
    Decodes a Graph API response body, tolerating a non-JSON one.

    Meta's error responses are JSON, but its gateway's 502/504 pages are HTML. Returning an
    empty dict lets `classify_graph_error` fall back to the HTTP status, which is the only
    signal such a response carries.
    """
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - a non-JSON body is expected from Meta's gateway
        return {}
    return body if isinstance(body, dict) else {}


def _first_message_id(body: dict[str, Any]) -> str | None:
    """
    Extracts the `wamid` Meta assigns to an accepted message.

    Meta returns `messages` as an array even though a single send produces exactly one
    entry. That id is what every subsequent delivery webhook keys on, so a send whose id we
    cannot read is untrackable — hence `_dispatch` treating its absence as a failure.
    """
    messages = body.get("messages")
    if isinstance(messages, list) and messages and isinstance(messages[0], dict):
        message_id = messages[0].get("id")
        return str(message_id) if message_id else None
    return None


def _backoff_delay(attempt: int, last: _GraphError | None) -> float:
    """
    Computes how long to wait before retry number `attempt`.

    Prefers a `Retry-After` Meta actually sent (carried on the error as its subcode slot is
    unused for rate limits — see `_with_retry_after`) over our own guess, then falls back to
    exponential backoff. Capped at 30 seconds: a campaign dispatches inside an HTTP request
    today, and a two-minute sleep would blow the request timeout for every recipient behind
    this one.
    """
    if last is not None and last.category == "rate_limit" and last.subcode:
        return float(min(last.subcode, 30))
    base = max(0.0, settings.WHATSAPP_RETRY_BACKOFF_SECONDS)
    return float(min(base * (2 ** (attempt - 1)), 30))


def _with_retry_after(error: _GraphError, response: Any) -> _GraphError:
    """
    Folds a `Retry-After` response header onto a rate-limit error so `_backoff_delay` can
    honour it.

    Stored in the unused `subcode` slot rather than in a new field, so the dataclass stays
    frozen and the retry path needs no extra plumbing. Only done for rate-limit errors,
    where the header is meaningful.
    """
    if error.category != "rate_limit":
        return error
    header = None
    try:
        header = response.headers.get("Retry-After")
    except Exception:  # noqa: BLE001 - a stub transport may not carry headers
        return error
    if not header:
        return error
    try:
        seconds = int(float(header))
    except (TypeError, ValueError):
        return error
    return _GraphError(
        message=error.message, code=error.code, subcode=max(0, seconds),
        http_status=error.http_status, retryable=True, category="rate_limit",
    )


def _normalize_language(language: str | None) -> str:
    """
    Converts a CRM language code into the locale form Meta registers templates under.

    Meta uses underscore-separated locales ("en_US"); the CRM's `language` column holds
    BCP-47-ish codes that may use a hyphen. Bare codes ("en") pass through untouched, since
    Meta accepts those too and guessing a region would find the wrong template.
    """
    code = (language or "en").strip()
    return code.replace("-", "_") if code else "en"


def _parse_epoch(value: Any) -> datetime | None:
    """
    Converts Meta's Unix-second timestamps (delivered as strings) into aware datetimes.

    Returns None on anything unparseable, letting the caller fall back to "now" rather than
    rejecting an otherwise-good event over a timestamp.
    """
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    """
    Coerces a possibly-missing, possibly-wrongly-typed webhook field into a dict.

    The companion to `_as_list`, and needed for the same reason: `value or {}` guards None
    but happily lets a string through to the next `.get()`, which then raises. A raising
    parser means Meta retries the webhook indefinitely, so every nested access goes through
    this.
    """
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """
    Coerces a possibly-missing, possibly-scalar webhook field into a list.

    Meta's arrays are reliably arrays today, but a defensive coercion here is what keeps a
    shape change from raising inside the parser — and a webhook that raises is one Meta
    retries indefinitely.
    """
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _redact_phone(phone: str | None) -> str:
    """
    Masks all but the last four digits of a number for logging.

    Campaign logs record one line per recipient and are read by more people than the CRM
    itself is; a full phone number in a log line is a lead's personal data sitting outside
    the access controls that protect the `leads` table.
    """
    if not phone:
        return "<none>"
    digits = _NON_DIGITS.sub("", phone)
    if len(digits) <= 4:
        return "*" * len(digits)
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"
