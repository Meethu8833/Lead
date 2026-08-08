"""
app/services/whatsapp_provider.py

This file defines the provider abstraction for outbound WhatsApp messaging, plus the
no-op provider used until a real integration is commissioned.
Under Clean Architecture, the abstract base class here is the *port*: the campaign service
depends on this interface and never on a concrete vendor. Concrete providers (WhatsApp
Cloud API, Twilio, Interakt, AiSensy) are *adapters* that will be added as sibling classes
in this file or in their own modules, and selected at runtime by `get_whatsapp_provider`.

Why the interface is this narrow
--------------------------------
`send_message` takes a destination number and an already-rendered message string, and
returns a `ProviderSendResult`. It deliberately does NOT take a template ID, a component
array, or any per-vendor payload shape, because those differ irreconcilably between
vendors: Meta wants a registered template name plus positional components, Twilio wants a
`Body` string, Interakt wants its own campaign JSON. Rendering the final text in our own
service (see `WhatsAppTemplateService.render`) and handing every provider a plain string
is the only contract all four can satisfy. A vendor that requires pre-registered templates
can map our template name onto its own inside its adapter.

Failure contract
----------------
An adapter must NOT raise for an ordinary per-message rejection (invalid number, opted-out
recipient, rate limit). It returns `ProviderSendResult(success=False, error=...)` so the
campaign run can mark that one recipient FAILED and carry on with the rest. Raising is
reserved for genuinely campaign-wide faults (bad credentials, provider unreachable), which
the campaign service catches per recipient anyway so that one poisoned row cannot abort a
10,000-lead send.

The four-method surface
-----------------------
`send_message` is the only method the campaign service calls, and it stays the narrow
string-in contract described above. The other three are the operational surface a real
vendor integration needs, added as *concrete* methods with working defaults rather than as
abstract ones, so that adding them cannot break an existing adapter:

- `send_template` sends a pre-registered template by name with positional parameters. This
  is what vendors like Meta require for business-initiated messaging outside a customer
  service window; the default implementation renders nothing and delegates to
  `send_message`, which is correct for free-text vendors.
- `get_message_status` polls a provider for one message's delivery state, for reconciling
  after a missed webhook. The default returns None ("this vendor cannot be polled"),
  which is the honest answer for most of them.
- `validate_configuration` reports whether the adapter's credentials are complete and
  coherent, without performing network I/O. It is what lets an operator find a missing
  credential from a status endpoint instead of from a failed campaign.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderSendResult:
    """
    The outcome of handing one message to a provider.

    Attributes:
        success: Whether the provider accepted the message for delivery. Acceptance is not
            delivery — the provider reports delivery later, asynchronously, via webhook.
        message_id: Opaque provider-assigned identifier, stored on the recipient row as
            `provider_message_id` and used to match inbound status webhooks back to it.
            Populated only on success.
        error: Human-readable rejection reason, stored as `error_message`. Populated only
            on failure.
        provider: Name of the adapter that produced this result, for diagnostics.
    """
    success: bool
    message_id: str | None = None
    error: str | None = None
    provider: str = "unknown"
    #: Whether the failure is worth retrying later. False for a permanent rejection (an
    #: invalid number, a template that does not exist); True for a transient one (rate
    #: limit, timeout, provider 5xx). The campaign service does not act on this today —
    #: it marks the recipient FAILED either way — but recording it lets a future
    #: "retry failed recipients" action distinguish the two without re-deriving the
    #: reason from an error string.
    retryable: bool = False
    #: Vendor-specific error code, kept alongside the human-readable `error` so an
    #: operator can look it up in the vendor's documentation.
    error_code: str | None = None


@dataclass(frozen=True)
class ProviderConfigurationResult:
    """
    The outcome of checking an adapter's configuration, without any network I/O.

    A dataclass rather than a bare bool because "misconfigured" is only actionable if it
    says *what* is missing. `missing` names the environment variables that are unset, and
    `warnings` carries the things that are set but questionable (signature verification
    disabled, a template-less deployment), which should be visible without failing the
    check.
    """
    valid: bool
    provider: str = "unknown"
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detail: str | None = None

    def as_message(self) -> str:
        """
        Renders the result as one operator-readable line, suitable for an error message on
        a refused send or a log entry at startup.
        """
        if self.valid:
            base = f"Provider '{self.provider}' is configured."
        else:
            base = (
                f"Provider '{self.provider}' is not configured: "
                f"{', '.join(self.missing)} {'are' if len(self.missing) != 1 else 'is'} unset."
                if self.missing
                else f"Provider '{self.provider}' is not configured."
            )
        if self.detail:
            base = f"{base} {self.detail}"
        if self.warnings:
            base = f"{base} Warnings: {'; '.join(self.warnings)}."
        return base


@dataclass(frozen=True)
class ProviderMessageStatus:
    """
    A provider's answer to "what happened to this message".

    `status` is the vendor's own raw status string, deliberately not translated to
    `MessageStatus` here: this module must stay free of any dependency on the campaign
    domain model, and the translation is the adapter's job at the point where it hands the
    result to the service layer.
    """
    message_id: str
    status: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class WhatsAppProvider(ABC):
    """
    Abstract base class every WhatsApp sending adapter must implement.

    Implementations must be safe to construct once and reuse across requests: the campaign
    service resolves a provider per run, not per message.
    """

    #: Short stable identifier for this adapter, recorded on send results.
    name: str = "abstract"

    @abstractmethod
    async def send_message(
        self,
        phone: str,
        message: str,
        *,
        template_name: str | None = None,
        language: str = "en",
    ) -> ProviderSendResult:
        """
        Delivers one fully-rendered message to one destination number.

        Args:
            phone: Destination number in whatever format the CRM stores it. Adapters are
                responsible for normalising to their vendor's expected format (e.g. E.164),
                because that normalisation is vendor-specific.
            message: The final message text, with all template variables already
                substituted. Adapters must send this verbatim.
            template_name: The source template's name, for vendors that require a
                pre-registered template identifier rather than free text. Ignored by
                vendors that accept free text.
            language: The source template's language code, for the same reason.

        Returns:
            ProviderSendResult describing acceptance or per-message rejection.
        """
        raise NotImplementedError

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
        Sends a pre-registered template message by name.

        Args:
            phone: Destination number, normalised by the adapter.
            template_name: The vendor-side registered template's name.
            language: The template's registered language code.
            parameters: Positional values for the template's body placeholders, in the
                order the vendor expects them. Positional rather than named because Meta's
                template components are positional and named parameters are a newer opt-in
                that not every registered template uses.
            header_parameters: Positional values for a text header's placeholders, if any.
            fallback_text: A fully-rendered version of the message, used by adapters that
                do not support registered templates at all.

        Returns:
            ProviderSendResult, under the same failure contract as `send_message`.

        The default implementation delegates to `send_message` with `fallback_text`, which
        is the correct behaviour for a vendor that accepts free text and has no template
        registry. Adapters whose vendor requires templates must override it.
        """
        return await self.send_message(
            phone,
            fallback_text or "",
            template_name=template_name,
            language=language,
        )

    async def get_message_status(self, message_id: str) -> ProviderMessageStatus | None:
        """
        Fetches the current delivery state of one previously-sent message.

        Returns None when the provider offers no way to poll a message's state, which is
        the case for most WhatsApp vendors including Meta: delivery state is pushed by
        webhook and there is no read-back endpoint. Callers must treat None as "unknown,
        keep waiting for the webhook" rather than as a failure.
        """
        return None

    async def validate_configuration(self) -> ProviderConfigurationResult:
        """
        Reports whether this adapter's credentials are complete, without network I/O.

        Deliberately offline: an operator checking configuration at startup or from a
        status endpoint should get an instant, deterministic answer, and a vendor being
        briefly unreachable is not a configuration error. Reachability is `health_check`'s
        job.
        """
        return ProviderConfigurationResult(valid=True, provider=self.name)

    async def health_check(self) -> bool:
        """
        Reports whether the provider is usable right now (credentials valid, endpoint
        reachable). The default implementation assumes healthy; real adapters should
        override it so a campaign can fail fast instead of marking every recipient FAILED
        one at a time.
        """
        return True


class NoOpWhatsAppProvider(WhatsAppProvider):
    """
    The default provider: records that a send was requested and reports success without
    contacting any external service.

    This exists so the entire campaign pipeline — dispatch, status transitions, counters,
    statistics, replies, lead-status automation — is exercisable and testable end to end
    before any vendor contract is signed. Swapping in a real adapter later changes exactly
    one thing: which class `get_whatsapp_provider` returns.

    It fabricates a syntactically plausible message ID so that the webhook-matching path
    (`provider_message_id` lookup) is genuinely exercised rather than bypassed in tests.
    """

    name = "noop"

    async def send_message(
        self,
        phone: str,
        message: str,
        *,
        template_name: str | None = None,
        language: str = "en",
    ) -> ProviderSendResult:
        """
        Simulates a successful send and returns a synthetic message ID.
        """
        message_id = f"noop-{uuid.uuid4()}"
        logger.info(
            "NoOpWhatsAppProvider: simulated send to %s (template=%s, lang=%s, %d chars) -> %s",
            phone,
            template_name,
            language,
            len(message),
            message_id,
        )
        return ProviderSendResult(
            success=True,
            message_id=message_id,
            provider=self.name,
        )


# Registry of available adapters, keyed by the identifier used to select one.
# Real adapters register themselves here as they are implemented; nothing else in the
# codebase needs to change to adopt one.
_PROVIDER_REGISTRY: dict[str, type[WhatsAppProvider]] = {
    NoOpWhatsAppProvider.name: NoOpWhatsAppProvider,
}


def register_whatsapp_provider(
    provider_cls: type[WhatsAppProvider],
) -> type[WhatsAppProvider]:
    """
    Registers a concrete provider adapter under its `name`, making it selectable by
    `get_whatsapp_provider`.

    Returns the class unchanged so it can be used as a class decorator (as the Cloud API
    adapter does), matching the `@register_provider` idiom the lead-collection providers
    already use.
    """
    _PROVIDER_REGISTRY[provider_cls.name] = provider_cls
    return provider_cls


def _load_builtin_adapters() -> None:
    """
    Imports the concrete adapter modules for their registration side effect.

    Deferred to call time rather than done at module import, because the adapters import
    `app.core.config` and (lazily) `httpx`, while this module is imported by the campaign
    service at startup. Keeping the port free of adapter imports is what stops a broken or
    absent optional dependency from taking the whole API down, and it is the same
    deferred-import discipline the lead-collection providers use.
    """
    try:
        import app.services.whatsapp_cloud  # noqa: F401,PLC0415 - imported for its side effect
    except Exception:  # noqa: BLE001 - a broken adapter must not break provider resolution
        logger.exception(
            "Failed to import the WhatsApp Cloud API adapter; it will not be selectable."
        )


def get_whatsapp_provider(name: str | None = None) -> WhatsAppProvider:
    """
    Resolves the provider adapter to use.

    With no argument the adapter named by `settings.WHATSAPP_PROVIDER` is returned, which
    defaults to the no-op provider — so adding a real adapter to the codebase does not by
    itself start sending real messages; an operator opts in through the environment.

    Falls back to the no-op provider when the requested adapter is unknown, rather than
    raising: an unconfigured or misconfigured provider name should degrade a campaign to a
    simulated send that is fully visible in the recipient records, not take the API down.
    The fallback is logged at WARNING so the misconfiguration is not silent.
    """
    if name is None:
        # Read at call time, not at import, so a test can monkeypatch the setting.
        from app.core.config import settings  # noqa: PLC0415 - deferred, see above
        name = settings.WHATSAPP_PROVIDER

    key = (name or NoOpWhatsAppProvider.name).strip().lower()

    if key not in _PROVIDER_REGISTRY:
        _load_builtin_adapters()

    provider_cls = _PROVIDER_REGISTRY.get(key)
    if provider_cls is None:
        logger.warning(
            "Unknown WhatsApp provider '%s'; falling back to the no-op provider. "
            "Registered providers: %s",
            name,
            sorted(_PROVIDER_REGISTRY),
        )
        provider_cls = NoOpWhatsAppProvider
    return provider_cls()
