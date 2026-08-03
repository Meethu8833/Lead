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
"""

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

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


def register_whatsapp_provider(provider_cls: type[WhatsAppProvider]) -> None:
    """
    Registers a concrete provider adapter under its `name`, making it selectable by
    `get_whatsapp_provider`.
    """
    _PROVIDER_REGISTRY[provider_cls.name] = provider_cls


def get_whatsapp_provider(name: str | None = None) -> WhatsAppProvider:
    """
    Resolves the provider adapter to use.

    Falls back to the no-op provider when the requested adapter is unknown, rather than
    raising: an unconfigured or misconfigured provider name should degrade a campaign to a
    simulated send that is fully visible in the recipient records, not take the API down.
    The fallback is logged at WARNING so the misconfiguration is not silent.
    """
    key = (name or NoOpWhatsAppProvider.name).strip().lower()
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
