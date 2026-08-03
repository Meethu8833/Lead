"""
tests/test_whatsapp.py

Integration test suite for the WhatsApp Campaign Management module.
Verifies:
1.  Template CRUD (create, uniqueness, variable extraction, read, list/filter, update
    + optimistic locking, soft delete, in-use deletion refusal).
2.  Template rendering (substitution, missing placeholders left verbatim, no recursive
    expansion of values, lead-derived variable mapping).
3.  Campaign CRUD (create as DRAFT/SCHEDULED, inactive-template refusal, read, list/filter,
    update + optimistic locking, immutability once running, delete rules).
4.  Recipient creation (enrolment at create time and afterwards, de-duplication, skipping
    deleted/unknown leads, whatsapp-number preference, removal rules).
5.  Campaign execution (dispatch through the provider port, per-recipient failure isolation,
    lifecycle transitions, no double-send on re-run, empty-campaign refusal).
6.  Campaign statistics (cumulative counts, rates, progress, empty-campaign zeros, and
    agreement with the denormalized counters).
7.  Reply recording (match by provider_message_id and by phone, recipient state, reply body
    and timestamp).
8.  Lead status update from replies (all three mappings, explicit override, unknown type,
    converted-lead protection).
9.  Activity creation (WHATSAPP_SENT on dispatch, WHATSAPP_REPLIED on reply,
    WHATSAPP_DELIVERED/READ on status callbacks, STATUS_CHANGED alongside an automated
    status move).
10. Lead.last_contacted_at maintenance on both dispatch and reply.
11. Delivery-status webhooks (forward-only/monotonic transitions, idempotency under replay).
12. Provider abstraction (no concrete provider referenced; a failing double is honoured;
    unknown provider names fall back to no-op).
13. RBAC (whatsapp:view / create / update / delete enforced, Administrator bypass,
    a leads-only role is refused).

This suite talks to the real configured database (see CLAUDE.md). Every row it creates is
explicitly hard-deleted in a `finally` block at the end, since the repository layer commits
each write immediately (a session-level rollback would not undo already-committed work).
Deleting the parent Campaign/Lead rows cascades away their recipients and activities.
"""

import asyncio
import sys
import os
import random
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, delete

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.core.context import audit_context
from app.core.exceptions import (
    BadRequestException,
    NotFoundException,
    ConflictException,
    ForbiddenException,
)
from app.models.lead import Lead, LeadStatus, LeadSource
from app.models.lead_activity import LeadActivity, ActivityType
from app.models.employee import Employee
from app.models.role import Role
from app.models.whatsapp import (
    WhatsAppTemplate,
    WhatsAppCampaign,
    CampaignRecipient,
    TemplateCategory,
    CampaignStatus,
    MessageStatus,
)
from app.schemas.lead import LeadCreate, LeadUpdate
from app.schemas.employee import EmployeeCreate
from app.schemas.whatsapp import (
    WhatsAppTemplateCreate,
    WhatsAppTemplateUpdate,
    WhatsAppCampaignCreate,
    WhatsAppCampaignUpdate,
    extract_template_variables,
)
from app.services.lead import LeadService
from app.services.lead_activity import LeadActivityService
from app.services.employee import EmployeeService
from app.services.whatsapp import (
    WhatsAppTemplateService,
    WhatsAppCampaignService,
    CampaignReplyService,
    REPLY_TYPE_TO_LEAD_STATUS,
)
from app.services.whatsapp_provider import (
    WhatsAppProvider,
    NoOpWhatsAppProvider,
    ProviderSendResult,
    get_whatsapp_provider,
)
from app.repositories.whatsapp import CampaignRecipientRepository
from app.api.deps import RequirePermission


def random_phone() -> str:
    return "".join(random.choices("0123456789", k=10))


class RecordingProvider(WhatsAppProvider):
    """
    Test double that records every send and reports success, so a campaign run can be
    asserted against exactly what was handed to the provider port.
    """
    name = "recording"

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, phone, message, *, template_name=None, language="en"):
        self.sent.append({
            "phone": phone, "message": message,
            "template_name": template_name, "language": language,
        })
        return ProviderSendResult(
            success=True, message_id=f"rec-{uuid.uuid4()}", provider=self.name
        )


class FailingProvider(WhatsAppProvider):
    """
    Test double that rejects every message, exercising the per-recipient failure path
    without raising (the contract an adapter must honour for ordinary rejections).
    """
    name = "failing"

    async def send_message(self, phone, message, *, template_name=None, language="en"):
        return ProviderSendResult(
            success=False, error="Recipient has opted out.", provider=self.name
        )


class ExplodingProvider(WhatsAppProvider):
    """
    Test double that raises on the second message, proving one poisoned recipient does not
    abort the whole run.
    """
    name = "exploding"

    def __init__(self) -> None:
        self.calls = 0

    async def send_message(self, phone, message, *, template_name=None, language="en"):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("Simulated provider outage")
        return ProviderSendResult(
            success=True, message_id=f"exp-{uuid.uuid4()}", provider=self.name
        )


async def test_whatsapp_suite():
    print("=== STARTING WHATSAPP CAMPAIGN INTEGRATION TESTS ===")

    lead_service = LeadService()
    activity_service = LeadActivityService()
    employee_service = EmployeeService()
    template_service = WhatsAppTemplateService()
    campaign_service = WhatsAppCampaignService()
    reply_service = CampaignReplyService()
    recipient_repo = CampaignRecipientRepository()

    unique_suffix = str(uuid.uuid4())[:8]
    marker = f"WACampaign{unique_suffix}"

    created_lead_ids: list[uuid.UUID] = []
    created_employee_ids: list[uuid.UUID] = []
    created_campaign_ids: list[uuid.UUID] = []
    created_template_ids: list[uuid.UUID] = []

    async with AsyncSessionLocal() as db:
        try:
            # ==========================================================
            # [0] SETUP: roles, employees, leads, acting-user context
            # ==========================================================
            print("\n--- [0] SETUP: ROLES, EMPLOYEES, LEADS & AUDIT CONTEXT ---")
            admin_role = (await db.execute(select(Role).where(Role.name == "Administrator"))).scalars().first()
            manager_role = (await db.execute(select(Role).where(Role.name == "Manager"))).scalars().first()
            designer_role = (await db.execute(select(Role).where(Role.name == "Designer"))).scalars().first()
            assert admin_role is not None and manager_role is not None and designer_role is not None

            actor = await employee_service.create_employee(db, EmployeeCreate(
                first_name="WhatsAppActor", last_name="Test",
                email=f"wa_actor_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=admin_role.id,
            ))
            created_employee_ids.append(actor.id)

            manager_employee = await employee_service.create_employee(db, EmployeeCreate(
                first_name="WhatsAppManager", last_name="Test",
                email=f"wa_manager_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=manager_role.id,
            ))
            created_employee_ids.append(manager_employee.id)

            # Designer has production/orders permissions but no whatsapp:* — the negative
            # case that proves campaign access is not implied by other CRM access.
            designer_employee = await employee_service.create_employee(db, EmployeeCreate(
                first_name="WhatsAppDesigner", last_name="Test",
                email=f"wa_designer_{unique_suffix}@colourlabs.com",
                phone=random_phone(), password="SecurePassword123!", role_id=designer_role.id,
            ))
            created_employee_ids.append(designer_employee.id)

            audit_context.set({
                "user_id": str(actor.id),
                "ip_address": "192.168.1.90",
                "user_agent": "Mozilla/5.0 (WhatsApp Campaign Test Agent)",
            })

            leads: list[Lead] = []
            for i in range(5):
                lead = await lead_service.create_lead(db, LeadCreate(
                    business_name=f"{marker} Studio {i}", phone=random_phone(),
                    contact_person=f"Contact {i}", city="Chennai", source=LeadSource.GOOGLE_MAPS,
                ))
                created_lead_ids.append(lead.id)
                leads.append(lead)
            lead_ids = [l.id for l in leads]
            print(f"Created 3 employees and {len(leads)} leads; acting employee = {actor.id}")

            # ==========================================================
            # [1] TEMPLATE CRUD
            # ==========================================================
            print("\n--- [1] TESTING TEMPLATE CRUD ---")
            template = await template_service.create_template(db, WhatsAppTemplateCreate(
                name=f"{marker} Intro",
                category=TemplateCategory.MARKETING,
                language="en",
                message_body="Hi {{contact_person}}, this is Colour Labs reaching out to {{business_name}} in {{city}}!",
            ))
            created_template_ids.append(template.id)
            assert template.id is not None
            assert template.is_active is True and template.version == 1
            print(f"Template created: {template.name}")

            # variables must be derived from the body, not supplied by the client
            assert template.variables == ["contact_person", "business_name", "city"], \
                f"Variables not extracted in order: {template.variables}"
            print(f"Variables auto-extracted from body: {template.variables}")

            # duplicate name rejected (case-insensitively)
            try:
                await template_service.create_template(db, WhatsAppTemplateCreate(
                    name=f"{marker} intro", message_body="Duplicate attempt.",
                ))
                assert False, "Duplicate template name did not raise"
            except BadRequestException:
                print("Duplicate template name rejected (case-insensitive).")

            fetched = await template_service.get_template_by_id(db, template.id)
            assert fetched.id == template.id

            try:
                await template_service.get_template_by_id(db, uuid.uuid4())
                assert False, "Unknown template ID did not raise NotFoundException"
            except NotFoundException:
                print("Unknown template ID raises 404.")

            items, total = await template_service.get_all_templates(db, search=marker)
            assert total >= 1 and any(t.id == template.id for t in items)
            items, cat_total = await template_service.get_all_templates(
                db, search=marker, category=TemplateCategory.UTILITY
            )
            assert cat_total == 0, "Category filter did not exclude the MARKETING template"
            print("Template listing, search and category filtering work.")

            # update: body edit must re-derive variables
            template = await template_service.update_template(db, template.id, WhatsAppTemplateUpdate(
                message_body="Hello {{business_name}}! Special offer for {{city}} studios.",
                version=template.version,
            ))
            assert template.variables == ["business_name", "city"], \
                f"Variables not re-derived on body edit: {template.variables}"
            assert template.version == 2
            print(f"Body edit re-derived variables: {template.variables}")

            # optimistic locking
            try:
                await template_service.update_template(db, template.id, WhatsAppTemplateUpdate(
                    name="Stale write", version=1,
                ))
                assert False, "Stale template version did not raise ConflictException"
            except ConflictException:
                print("Template optimistic locking enforced.")

            # ==========================================================
            # [2] TEMPLATE RENDERING
            # ==========================================================
            print("\n--- [2] TESTING TEMPLATE RENDERING ---")
            rendered, missing = template_service.render(
                "Hi {{name}}, welcome to {{city}}!", {"name": "Asha", "city": "Chennai"}
            )
            assert rendered == "Hi Asha, welcome to Chennai!", rendered
            assert missing == []
            print("Substitution renders all supplied variables.")

            rendered, missing = template_service.render(
                "Hi {{name}}, welcome to {{city}}!", {"name": "Asha"}
            )
            assert rendered == "Hi Asha, welcome to {{city}}!", rendered
            assert missing == ["city"], missing
            print("Missing placeholders left verbatim and reported.")

            # A value containing a placeholder must not be re-expanded (no template injection).
            rendered, _ = template_service.render(
                "Hi {{name}}!", {"name": "{{city}}", "city": "SHOULD-NOT-APPEAR"}
            )
            assert rendered == "Hi {{city}}!", rendered
            assert "SHOULD-NOT-APPEAR" not in rendered
            print("Variable values are not recursively expanded (no template injection).")

            lead_vars = template_service.build_lead_variables(leads[0])
            assert lead_vars["business_name"] == leads[0].business_name
            assert lead_vars["contact_person"] == leads[0].contact_person
            assert extract_template_variables("no placeholders here") == []
            print("Lead-derived variable mapping built correctly.")

            # ==========================================================
            # [3] CAMPAIGN CRUD + RECIPIENT CREATION
            # ==========================================================
            print("\n--- [3] TESTING CAMPAIGN CRUD & RECIPIENT CREATION ---")
            campaign = await campaign_service.create_campaign(db, WhatsAppCampaignCreate(
                template_id=template.id,
                name=f"{marker} Launch",
                description="Outreach to Chennai studios.",
                lead_ids=lead_ids[:3],
            ))
            created_campaign_ids.append(campaign.id)
            assert campaign.status == CampaignStatus.DRAFT, "Campaign without a schedule must start DRAFT"
            assert campaign.total_recipients == 3, f"Expected 3 recipients, got {campaign.total_recipients}"
            assert campaign.created_by == actor.id, "Campaign must be attributed to the acting employee"
            campaign_id = campaign.id
            print(f"Campaign created as DRAFT with {campaign.total_recipients} recipients.")

            recips, r_total = await campaign_service.get_recipients(db, campaign_id)
            assert r_total == 3
            assert all(r.message_status == MessageStatus.PENDING for r in recips)
            assert {r.lead_id for r in recips} == set(lead_ids[:3])
            print("Recipient rows created PENDING, one per enrolled lead.")

            # scheduled campaign starts SCHEDULED
            future = datetime.now(timezone.utc) + timedelta(days=1)
            scheduled_campaign = await campaign_service.create_campaign(db, WhatsAppCampaignCreate(
                template_id=template.id, name=f"{marker} Scheduled",
                scheduled_at=future, lead_ids=[lead_ids[3]],
            ))
            created_campaign_ids.append(scheduled_campaign.id)
            assert scheduled_campaign.status == CampaignStatus.SCHEDULED, \
                "Campaign with scheduled_at must start SCHEDULED"
            assert scheduled_campaign.scheduled_at is not None
            print("Campaign with scheduled_at starts SCHEDULED.")

            # de-duplication: re-adding enrolled leads adds nothing
            campaign, added = await campaign_service.add_recipients(db, campaign_id, lead_ids[:3])
            assert added == 0, f"Re-adding enrolled leads should add 0, added {added}"
            assert campaign.total_recipients == 3
            print("Re-enrolling existing leads is a no-op (de-duplicated).")

            # adding a new lead works; unknown IDs are skipped, not fatal
            campaign, added = await campaign_service.add_recipients(
                db, campaign_id, [lead_ids[3], uuid.uuid4()]
            )
            assert added == 1, f"Expected 1 new recipient (unknown ID skipped), added {added}"
            assert campaign.total_recipients == 4
            print("New lead enrolled; unknown lead ID skipped rather than failing the request.")

            # inactive template cannot back a new campaign
            inactive_tpl = await template_service.create_template(db, WhatsAppTemplateCreate(
                name=f"{marker} Inactive", message_body="Inactive body.", is_active=False,
            ))
            created_template_ids.append(inactive_tpl.id)
            try:
                await campaign_service.create_campaign(db, WhatsAppCampaignCreate(
                    template_id=inactive_tpl.id, name=f"{marker} ShouldFail",
                ))
                assert False, "Inactive template did not block campaign creation"
            except BadRequestException:
                print("Inactive template cannot back a new campaign.")

            # template in use cannot be deleted
            try:
                await template_service.delete_template(db, template.id)
                assert False, "In-use template deletion did not raise"
            except BadRequestException:
                print("In-use template deletion refused with a clear error.")

            # campaign update + optimistic locking
            campaign = await campaign_service.update_campaign(db, campaign_id, WhatsAppCampaignUpdate(
                name=f"{marker} Launch v2", version=campaign.version,
            ))
            assert campaign.name == f"{marker} Launch v2"
            try:
                await campaign_service.update_campaign(db, campaign_id, WhatsAppCampaignUpdate(
                    name="Stale", version=1,
                ))
                assert False, "Stale campaign version did not raise ConflictException"
            except ConflictException:
                print("Campaign optimistic locking enforced.")

            # recipient removal rules
            pending_recips, _ = await campaign_service.get_recipients(db, campaign_id)
            removable = pending_recips[-1]
            campaign = await campaign_service.remove_recipient(db, campaign_id, removable.id)
            assert campaign.total_recipients == 3, "Counter not refreshed after recipient removal"
            campaign, _ = await campaign_service.add_recipients(db, campaign_id, [removable.lead_id])
            assert campaign.total_recipients == 4
            print("PENDING recipient removed and re-added; counters stay consistent.")

            # ==========================================================
            # [4] CAMPAIGN EXECUTION (DISPATCH)
            # ==========================================================
            print("\n--- [4] TESTING CAMPAIGN EXECUTION ---")
            # Empty campaign refuses to start.
            empty_campaign = await campaign_service.create_campaign(db, WhatsAppCampaignCreate(
                template_id=template.id, name=f"{marker} Empty",
            ))
            created_campaign_ids.append(empty_campaign.id)
            try:
                await campaign_service.start_campaign(db, empty_campaign.id)
                assert False, "Starting a campaign with no recipients did not raise"
            except BadRequestException:
                print("Campaign with no recipients refuses to start.")

            recording = RecordingProvider()
            recording_service = WhatsAppCampaignService(provider=recording)
            result = await recording_service.start_campaign(db, campaign_id)

            assert result["succeeded"] == 4, f"Expected 4 successful sends, got {result['succeeded']}"
            assert result["failed"] == 0
            assert result["provider"] == "recording"
            assert len(recording.sent) == 4, "Provider port did not receive one call per recipient"
            print(f"Dispatched 4 messages through the provider port ({result['provider']}).")

            # the provider received the RENDERED body, personalised per lead
            sent_messages = [s["message"] for s in recording.sent]
            assert all("{{" not in m for m in sent_messages), \
                f"Unrendered placeholder leaked to the provider: {sent_messages}"
            assert any(leads[0].business_name in m for m in sent_messages), \
                "Message was not personalised with the lead's business name"
            assert all(s["template_name"] == template.name for s in recording.sent)
            print("Provider received fully-rendered, per-lead personalised bodies.")

            campaign = await campaign_service.get_campaign_by_id(db, campaign_id)
            assert campaign.status == CampaignStatus.COMPLETED, \
                f"Fully-dispatched campaign should be COMPLETED, is {campaign.status}"
            assert campaign.started_at is not None and campaign.completed_at is not None
            assert campaign.total_sent == 4, f"total_sent should be 4, is {campaign.total_sent}"
            print("Campaign auto-completed; counters updated.")

            recips, _ = await campaign_service.get_recipients(db, campaign_id)
            assert all(r.message_status == MessageStatus.SENT for r in recips)
            assert all(r.sent_at is not None for r in recips)
            assert all(r.provider_message_id for r in recips), "provider_message_id not stored"
            assert all(r.rendered_message and "{{" not in r.rendered_message for r in recips), \
                "rendered_message not snapshotted onto the recipient row"
            print("Recipients marked SENT with sent_at, provider_message_id and rendered snapshot.")

            # a COMPLETED campaign cannot be restarted (no double-send)
            try:
                await recording_service.start_campaign(db, campaign_id)
                assert False, "Restarting a COMPLETED campaign did not raise"
            except BadRequestException:
                print("COMPLETED campaign cannot be restarted (no double-send).")
            assert len(recording.sent) == 4, "A rejected restart still sent messages"

            # a COMPLETED campaign is immutable
            try:
                await campaign_service.update_campaign(db, campaign_id, WhatsAppCampaignUpdate(name="nope"))
                assert False, "Editing a COMPLETED campaign did not raise"
            except BadRequestException:
                print("COMPLETED campaign is immutable.")

            # ==========================================================
            # [5] LAST_CONTACTED_AT ON DISPATCH
            # ==========================================================
            print("\n--- [5] TESTING Lead.last_contacted_at ON DISPATCH ---")
            for lead_id in lead_ids[:4]:
                refreshed = await db.get(Lead, lead_id)
                await db.refresh(refreshed)
                assert refreshed.last_contacted_at is not None, \
                    f"Lead {lead_id} was messaged but last_contacted_at is still null"
            untouched = await db.get(Lead, lead_ids[4])
            await db.refresh(untouched)
            assert untouched.last_contacted_at is None, \
                "A lead not in the campaign must not be stamped as contacted"
            print("last_contacted_at stamped for messaged leads only.")

            # ==========================================================
            # [6] ACTIVITY CREATION ON DISPATCH
            # ==========================================================
            print("\n--- [6] TESTING WHATSAPP_SENT ACTIVITY CREATION ---")
            acts, act_total = await activity_service.get_lead_timeline(
                db, lead_ids[0], activity_type=ActivityType.WHATSAPP_SENT
            )
            assert act_total == 1, f"Expected 1 WHATSAPP_SENT activity, got {act_total}"
            sent_act = acts[0]
            assert sent_act.activity_metadata["campaign_id"] == str(campaign_id)
            assert sent_act.activity_metadata["template_name"] == template.name
            assert sent_act.activity_metadata["provider"] == "recording"
            assert sent_act.created_by_employee_id == actor.id
            assert "{{" not in (sent_act.description or ""), "Activity recorded an unrendered body"
            print("WHATSAPP_SENT activity appended with campaign/template metadata.")

            # ==========================================================
            # [7] PROVIDER FAILURE ISOLATION
            # ==========================================================
            print("\n--- [7] TESTING PROVIDER FAILURE HANDLING ---")
            fail_campaign = await campaign_service.create_campaign(db, WhatsAppCampaignCreate(
                template_id=template.id, name=f"{marker} Failing", lead_ids=lead_ids[:2],
            ))
            created_campaign_ids.append(fail_campaign.id)
            failing_service = WhatsAppCampaignService(provider=FailingProvider())
            fail_result = await failing_service.start_campaign(db, fail_campaign.id)
            assert fail_result["succeeded"] == 0 and fail_result["failed"] == 2
            fail_recips, _ = await campaign_service.get_recipients(db, fail_campaign.id)
            assert all(r.message_status == MessageStatus.FAILED for r in fail_recips)
            assert all(r.error_message == "Recipient has opted out." for r in fail_recips), \
                "Provider rejection reason not stored on the recipient row"
            print("Provider rejections recorded per recipient with their reason.")

            # one raising recipient must not abort the run
            explode_campaign = await campaign_service.create_campaign(db, WhatsAppCampaignCreate(
                template_id=template.id, name=f"{marker} Exploding", lead_ids=lead_ids[:3],
            ))
            created_campaign_ids.append(explode_campaign.id)
            exploding_service = WhatsAppCampaignService(provider=ExplodingProvider())
            exp_result = await exploding_service.start_campaign(db, explode_campaign.id)
            assert exp_result["succeeded"] == 2 and exp_result["failed"] == 1, \
                f"Expected 2 ok / 1 failed, got {exp_result}"
            exp_recips, _ = await campaign_service.get_recipients(db, explode_campaign.id)
            failed_rows = [r for r in exp_recips if r.message_status == MessageStatus.FAILED]
            assert len(failed_rows) == 1
            assert "Simulated provider outage" in (failed_rows[0].error_message or "")
            print("A raising provider call fails only its own recipient; the run continues.")

            # ==========================================================
            # [8] CAMPAIGN STATISTICS
            # ==========================================================
            print("\n--- [8] TESTING CAMPAIGN STATISTICS ---")
            stats = await campaign_service.get_statistics(db, campaign_id)
            assert stats.total_recipients == 4
            assert stats.sent == 4 and stats.pending == 0 and stats.failed == 0
            assert stats.delivery_rate == 0.0, "Nothing is delivered yet"
            assert stats.progress_percent == 100.0, "All recipients dispatched -> 100% progress"
            print(f"Statistics after dispatch: sent={stats.sent}, progress={stats.progress_percent}%")

            empty_stats = await campaign_service.get_statistics(db, empty_campaign.id)
            assert empty_stats.total_recipients == 0
            assert empty_stats.delivery_rate == 0.0 and empty_stats.progress_percent == 0.0, \
                "Empty campaign must report 0.0 rates, not divide by zero"
            print("Empty campaign reports zeros rather than dividing by zero.")

            fail_stats = await campaign_service.get_statistics(db, fail_campaign.id)
            assert fail_stats.failed == 2 and fail_stats.failure_rate == 100.0
            print(f"Failed campaign reports failure_rate={fail_stats.failure_rate}%")

            # ==========================================================
            # [9] DELIVERY STATUS WEBHOOKS (MONOTONIC + IDEMPOTENT)
            # ==========================================================
            print("\n--- [9] TESTING DELIVERY STATUS WEBHOOKS ---")
            # Key recipients by lead_id rather than by list position. Bulk enrolment writes
            # every row inside one transaction, so they share an identical `created_at` and
            # the repository's `id` tiebreaker (a random UUID) decides their order — which
            # means list position is NOT stable across two reads of the same campaign.
            recips, _ = await campaign_service.get_recipients(db, campaign_id)
            by_lead = {r.lead_id: r for r in recips}
            assert len(by_lead) == 4, "Expected one recipient row per enrolled lead"

            target = by_lead[lead_ids[0]]
            pmid = target.provider_message_id

            updated = await campaign_service.apply_delivery_status(db, pmid, MessageStatus.DELIVERED)
            assert updated.message_status == MessageStatus.DELIVERED
            assert updated.delivered_at is not None
            print("DELIVERED callback applied with timestamp.")

            updated = await campaign_service.apply_delivery_status(db, pmid, MessageStatus.READ)
            assert updated.message_status == MessageStatus.READ and updated.read_at is not None
            print("READ callback applied with timestamp.")

            # out-of-order / replayed webhook must not regress the status
            read_at_before = updated.read_at
            updated = await campaign_service.apply_delivery_status(db, pmid, MessageStatus.DELIVERED)
            assert updated.message_status == MessageStatus.READ, \
                "A late DELIVERED webhook regressed a READ message"
            assert updated.read_at == read_at_before, "Replayed webhook rewrote a timestamp"
            print("Out-of-order/replayed callbacks are idempotent no-ops (monotonic status).")

            try:
                await campaign_service.apply_delivery_status(db, "does-not-exist", MessageStatus.DELIVERED)
                assert False, "Unknown provider_message_id did not raise NotFoundException"
            except NotFoundException:
                print("Unknown provider_message_id raises 404.")

            # delivery milestones append timeline entries
            _, delivered_acts = await activity_service.get_lead_timeline(
                db, target.lead_id, activity_type=ActivityType.WHATSAPP_DELIVERED
            )
            _, read_acts = await activity_service.get_lead_timeline(
                db, target.lead_id, activity_type=ActivityType.WHATSAPP_READ
            )
            assert delivered_acts == 1 and read_acts == 1, \
                f"Expected 1 DELIVERED + 1 READ activity, got {delivered_acts} + {read_acts}"
            print("WHATSAPP_DELIVERED and WHATSAPP_READ activities appended.")

            # cumulative statistics: a READ recipient still counts as sent and delivered
            stats = await campaign_service.get_statistics(db, campaign_id)
            assert stats.read == 1 and stats.delivered == 0 and stats.sent == 3
            assert stats.delivery_rate == 25.0, f"Cumulative delivery rate wrong: {stats.delivery_rate}"
            assert stats.read_rate == 25.0, f"Cumulative read rate wrong: {stats.read_rate}"
            print(f"Cumulative rates correct: delivery={stats.delivery_rate}%, read={stats.read_rate}%")

            # denormalized counters agree with the recomputed statistics
            campaign = await campaign_service.get_campaign_by_id(db, campaign_id)
            assert campaign.total_read == stats.read + stats.replied
            assert campaign.total_sent == 4, \
                f"Denormalized total_sent drifted from statistics: {campaign.total_sent}"
            print("Denormalized campaign counters agree with recomputed statistics.")

            # ==========================================================
            # [10] REPLY RECORDING + LEAD STATUS UPDATE + ACTIVITY
            # ==========================================================
            print("\n--- [10] TESTING REPLY RECORDING ---")
            # 10a. 'interested' -> NEGOTIATION, matched by provider_message_id
            interested_recip = by_lead[lead_ids[1]]
            reply_result = await reply_service.record_reply(
                db,
                reply_text="Yes, I'm interested. Please send your rate card.",
                provider_message_id=interested_recip.provider_message_id,
                reply_type="interested",
            )
            assert reply_result["recipient"].message_status == MessageStatus.REPLIED
            assert reply_result["recipient"].reply_text.startswith("Yes, I'm interested")
            assert reply_result["recipient"].replied_at is not None
            assert reply_result["lead_status"] == LeadStatus.NEGOTIATION, \
                f"'interested' must map to NEGOTIATION, got {reply_result['lead_status']}"
            assert reply_result["lead_status_changed"] is True
            assert reply_result["activity_id"] is not None
            print("Reply matched by provider_message_id: recipient REPLIED, lead -> NEGOTIATION.")

            replied_lead = await db.get(Lead, interested_recip.lead_id)
            await db.refresh(replied_lead)
            assert replied_lead.status == LeadStatus.NEGOTIATION, "Lead status not persisted"
            assert replied_lead.last_contacted_at is not None
            print("Lead status persisted and last_contacted_at re-stamped on reply.")

            # the reply must be visible on the timeline, with a STATUS_CHANGED alongside it
            _, replied_acts = await activity_service.get_lead_timeline(
                db, interested_recip.lead_id, activity_type=ActivityType.WHATSAPP_REPLIED
            )
            assert replied_acts == 1, f"Expected 1 WHATSAPP_REPLIED activity, got {replied_acts}"
            status_acts, status_total = await activity_service.get_lead_timeline(
                db, interested_recip.lead_id, activity_type=ActivityType.STATUS_CHANGED
            )
            assert status_total >= 1
            assert status_acts[0].activity_metadata["new_status"] == "NEGOTIATION"
            print("WHATSAPP_REPLIED and STATUS_CHANGED activities both appended.")

            # 10b. 'not_interested' -> LOST, matched by PHONE only.
            #
            # lead_ids[2] sits in three campaigns by this point (the main one plus the
            # failing and exploding runs above), so its number has several dispatch records.
            # The documented rule is that a phone-matched reply attaches to that number's
            # MOST RECENT dispatch, which is what a human reading the conversation would
            # assume. Assert exactly that, rather than assuming a particular campaign wins.
            not_interested_recip = by_lead[lead_ids[2]]
            expected_match = await recipient_repo.get_latest_for_phone(
                db, not_interested_recip.phone
            )
            assert expected_match is not None
            assert expected_match.lead_id == lead_ids[2], \
                "Phone lookup crossed over to a different lead's number"

            reply_result = await reply_service.record_reply(
                db,
                reply_text="No thanks, not interested.",
                phone=not_interested_recip.phone,
                reply_type="not_interested",
            )
            assert reply_result["recipient"].id == expected_match.id, \
                "Phone fallback did not attach the reply to the most recent dispatch"
            assert reply_result["lead_id"] == lead_ids[2], \
                "Phone fallback resolved to the wrong lead"
            assert reply_result["lead_status"] == LeadStatus.LOST, \
                f"'not_interested' must map to LOST, got {reply_result['lead_status']}"
            print("Reply matched by phone fallback (most recent dispatch): lead -> LOST.")

            # 10c. 'need_details' -> REPLIED
            need_details_recip = by_lead[lead_ids[3]]
            reply_result = await reply_service.record_reply(
                db,
                reply_text="Can you share more details?",
                provider_message_id=need_details_recip.provider_message_id,
                reply_type="need_details",
            )
            assert reply_result["lead_status"] == LeadStatus.REPLIED, \
                f"'need_details' must map to REPLIED, got {reply_result['lead_status']}"
            print("'need_details' maps to REPLIED.")

            # the specification's mapping, asserted directly
            assert REPLY_TYPE_TO_LEAD_STATUS == {
                "interested": LeadStatus.NEGOTIATION,
                "not_interested": LeadStatus.LOST,
                "need_details": LeadStatus.REPLIED,
            }
            print("Reply-type -> lead-status mapping matches the specification.")

            # 10d. reply counters
            #
            # 10a and 10c were matched by provider_message_id, so both landed on this
            # campaign for certain. 10b was matched by phone and may have attached to a
            # later campaign carrying the same number, so it is counted where it actually
            # landed rather than assumed here.
            stats = await campaign_service.get_statistics(db, campaign_id)
            replies_on_this_campaign = 2 + (1 if expected_match.campaign_id == campaign_id else 0)
            assert stats.replied == replies_on_this_campaign, \
                f"Expected {replies_on_this_campaign} replies, got {stats.replied}"
            assert stats.reply_rate == round((replies_on_this_campaign / 4) * 100, 2), \
                f"Reply rate wrong: {stats.reply_rate}"
            campaign = await campaign_service.get_campaign_by_id(db, campaign_id)
            assert campaign.total_replied == stats.replied, \
                "Denormalized total_replied drifted from the recomputed statistics"

            # Wherever it landed, the phone-matched reply must be recorded exactly once.
            landed = await recipient_repo.get_by_id(db, expected_match.id)
            assert landed.message_status == MessageStatus.REPLIED
            assert landed.reply_text == "No thanks, not interested."
            print(f"Reply statistics: replied={stats.replied}, reply_rate={stats.reply_rate}%")

            # ==========================================================
            # [11] REPLY EDGE CASES
            # ==========================================================
            print("\n--- [11] TESTING REPLY EDGE CASES ---")
            # unrecognised reply_type must not move the lead
            target_recip = by_lead[lead_ids[0]]
            lead_before = await db.get(Lead, target_recip.lead_id)
            await db.refresh(lead_before)
            status_before = lead_before.status
            reply_result = await reply_service.record_reply(
                db, reply_text="Maybe later.",
                provider_message_id=target_recip.provider_message_id,
                reply_type="some_unknown_intent",
            )
            assert reply_result["lead_status_changed"] is False
            assert reply_result["lead_status"] == status_before, \
                "An unrecognised reply_type silently reclassified the lead"
            print("Unrecognised reply_type leaves the lead's status untouched.")

            # explicit lead_status overrides the mapping
            reply_result = await reply_service.record_reply(
                db, reply_text="Actually, let's talk.",
                provider_message_id=target_recip.provider_message_id,
                reply_type="not_interested",           # would map to LOST...
                lead_status=LeadStatus.INTERESTED,      # ...but the explicit value wins
            )
            assert reply_result["lead_status"] == LeadStatus.INTERESTED, \
                "Explicit lead_status did not override the reply_type mapping"
            print("Explicit lead_status overrides the reply_type mapping.")

            # a converted lead must never be re-categorised by an inbound message
            converted_lead = await db.get(Lead, need_details_recip.lead_id)
            await db.refresh(converted_lead)
            converted_lead.status = LeadStatus.CUSTOMER
            converted_lead.is_converted = True
            db.add(converted_lead)
            await db.commit()

            reply_result = await reply_service.record_reply(
                db, reply_text="Thanks for the album!",
                provider_message_id=need_details_recip.provider_message_id,
                reply_type="not_interested",
            )
            assert reply_result["lead_status"] == LeadStatus.CUSTOMER, \
                "A reply demoted a converted CUSTOMER lead"
            assert reply_result["lead_status_changed"] is False
            print("A converted (CUSTOMER) lead is never re-categorised by a reply.")

            # unmatched reply raises
            try:
                await reply_service.record_reply(
                    db, reply_text="Hello?", provider_message_id="no-such-message-id",
                )
                assert False, "Unknown provider_message_id did not raise NotFoundException"
            except NotFoundException:
                print("Reply with an unknown provider_message_id raises 404.")

            try:
                await reply_service.record_reply(db, reply_text="Hello?", phone="0000000000")
                assert False, "Unknown phone did not raise NotFoundException"
            except NotFoundException:
                print("Reply from an unknown phone raises 404.")

            try:
                await reply_service.record_reply(db, reply_text="Hello?")
                assert False, "Reply with no identifier did not raise BadRequestException"
            except BadRequestException:
                print("Reply with neither provider_message_id nor phone raises 400.")

            # ==========================================================
            # [12] LIFECYCLE TRANSITIONS
            # ==========================================================
            print("\n--- [12] TESTING LIFECYCLE TRANSITIONS ---")
            cancel_campaign = await campaign_service.create_campaign(db, WhatsAppCampaignCreate(
                template_id=template.id, name=f"{marker} ToCancel", lead_ids=[lead_ids[4]],
            ))
            created_campaign_ids.append(cancel_campaign.id)
            cancelled = await campaign_service.cancel_campaign(db, cancel_campaign.id)
            assert cancelled.status == CampaignStatus.CANCELLED
            try:
                await campaign_service.start_campaign(db, cancel_campaign.id)
                assert False, "Starting a CANCELLED campaign did not raise"
            except BadRequestException:
                print("CANCELLED campaign cannot be started.")
            try:
                await campaign_service.cancel_campaign(db, cancel_campaign.id)
                assert False, "Re-cancelling a CANCELLED campaign did not raise"
            except BadRequestException:
                print("CANCELLED is terminal (cannot be re-cancelled).")

            # scheduling
            rescheduled = await campaign_service.schedule_campaign(
                db, scheduled_campaign.id, datetime.now(timezone.utc) + timedelta(days=3)
            )
            assert rescheduled.status == CampaignStatus.SCHEDULED
            try:
                await campaign_service.schedule_campaign(
                    db, scheduled_campaign.id, datetime.now(timezone.utc) - timedelta(days=1)
                )
                assert False, "Scheduling in the past did not raise"
            except BadRequestException:
                print("Scheduling a campaign in the past is refused.")

            # a scheduled campaign can still be started on demand
            start_result = await campaign_service.start_campaign(db, scheduled_campaign.id)
            assert start_result["succeeded"] == 1
            print("SCHEDULED campaign can be started on demand.")

            # soft delete rules
            await campaign_service.delete_campaign(db, cancel_campaign.id)
            try:
                await campaign_service.get_campaign_by_id(db, cancel_campaign.id)
                assert False, "Soft-deleted campaign is still readable"
            except NotFoundException:
                print("Soft-deleted campaign is excluded from reads.")

            # ==========================================================
            # [13] PROVIDER ABSTRACTION
            # ==========================================================
            print("\n--- [13] TESTING PROVIDER ABSTRACTION ---")
            default_provider = get_whatsapp_provider()
            assert isinstance(default_provider, NoOpWhatsAppProvider)
            assert isinstance(default_provider, WhatsAppProvider)
            print(f"Default provider is the no-op adapter ('{default_provider.name}').")

            fallback = get_whatsapp_provider("meta-cloud-api-not-implemented-yet")
            assert isinstance(fallback, NoOpWhatsAppProvider), \
                "Unknown provider name should fall back to the no-op adapter"
            print("Unknown provider name falls back to no-op rather than erroring.")

            noop_result = await default_provider.send_message("919000000000", "Hello there")
            assert noop_result.success is True and noop_result.message_id.startswith("noop-")
            assert await default_provider.health_check() is True
            print("No-op provider returns a synthetic message ID and reports healthy.")

            # the module must not name a concrete vendor anywhere
            import app.services.whatsapp as wa_service_module
            service_source = open(wa_service_module.__file__).read().lower()
            for vendor in ("twilio", "interakt", "aisensy", "graph.facebook.com"):
                assert vendor not in service_source, \
                    f"Campaign service references the concrete vendor '{vendor}'"
            print("Campaign service contains no concrete provider references.")

            # ==========================================================
            # [14] RBAC
            # ==========================================================
            print("\n--- [14] TESTING RBAC ---")
            from app.services.cache import permission_cache
            # The whatsapp:* permissions were seeded after this process may have warmed its
            # cache, so clear it and force the checks below to resolve from the database.
            await permission_cache.clear()

            dep_view = RequirePermission("whatsapp:view")
            dep_create = RequirePermission("whatsapp:create")
            dep_update = RequirePermission("whatsapp:update")
            dep_delete = RequirePermission("whatsapp:delete")

            # Administrator bypasses every check.
            for dep, label in [
                (dep_view, "whatsapp:view"), (dep_create, "whatsapp:create"),
                (dep_update, "whatsapp:update"), (dep_delete, "whatsapp:delete"),
            ]:
                res = await dep(db, actor, employee_service)
                assert res.id == actor.id, f"Administrator was denied {label}"
            print("RBAC: Administrator bypasses all whatsapp permission checks.")

            # Manager holds whatsapp:* and passes all four.
            for dep, label in [
                (dep_view, "whatsapp:view"), (dep_create, "whatsapp:create"),
                (dep_update, "whatsapp:update"), (dep_delete, "whatsapp:delete"),
            ]:
                res = await dep(db, manager_employee, employee_service)
                assert res.id == manager_employee.id, f"Manager was denied {label}"
            print("RBAC: Manager (whatsapp:*) is granted view/create/update/delete.")

            # Designer has no whatsapp permission at all — the key negative case.
            for dep, label in [
                (dep_view, "whatsapp:view"), (dep_create, "whatsapp:create"),
                (dep_update, "whatsapp:update"), (dep_delete, "whatsapp:delete"),
            ]:
                try:
                    await dep(db, designer_employee, employee_service)
                    assert False, f"Designer was wrongly granted {label}"
                except ForbiddenException:
                    pass
            print("RBAC: a role without whatsapp permissions is refused on all four actions.")

            # ==========================================================
            # [15] REGRESSION: EXISTING LEAD BEHAVIOUR UNCHANGED
            # ==========================================================
            print("\n--- [15] REGRESSION: EXISTING LEAD BEHAVIOUR ---")
            reg = await lead_service.create_lead(db, LeadCreate(
                business_name=f"{marker} Regression Co", phone=random_phone(),
                status=LeadStatus.INTERESTED,
            ))
            created_lead_ids.append(reg.id)
            assert reg.status == LeadStatus.NEW, "create_lead must still force status=NEW"
            assert reg.last_contacted_at is None, "A new lead must not be pre-stamped as contacted"
            assert reg.version == 1 and reg.is_deleted is False
            reg = await lead_service.update_lead(db, reg.id, LeadUpdate(
                remarks="Untouched by the campaign module.", version=reg.version,
            ))
            assert reg.version == 2
            found, found_total = await lead_service.get_all_leads(db, search=marker)
            assert found_total >= 5
            print(f"Lead CRUD unaffected by the campaign module ({found_total} leads match the marker).")

            print("\n=== ALL WHATSAPP CAMPAIGN INTEGRATION TESTS COMPLETED SUCCESSFULLY ===")

        except Exception as e:
            print(f"\nTEST SUITE FAILED WITH ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise e
        finally:
            # Repository writes commit immediately, so we explicitly hard-delete everything
            # this suite created, children first. Deleting a Campaign cascades its
            # recipients away; deleting a Lead cascades its activities and recipients away.
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
            for employee_id_ in created_employee_ids:
                row = await db.get(Employee, employee_id_)
                if row:
                    await db.delete(row)
            await db.commit()
            print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(test_whatsapp_suite())
