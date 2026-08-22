from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.business.service import BusinessNameConflict
from foundora.infrastructure.database import get_session_factory
from foundora.models import ApprovedBusinessProfile, Business, BusinessOnboardingDraft


class OnboardingRevisionConflict(Exception):
    pass


class OnboardingStateConflict(Exception):
    pass


class OnboardingIncomplete(Exception):
    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = missing_fields
        super().__init__(", ".join(missing_fields))


@dataclass(frozen=True)
class OnboardingState:
    business: Business
    draft: BusinessOnboardingDraft | None
    approved_profile: ApprovedBusinessProfile | None


def _now() -> datetime:
    return datetime.now(UTC)


def missing_required_fields(draft: BusinessOnboardingDraft) -> list[str]:
    required_scalars = {
        "business type": draft.business_type,
        "business name": draft.business_name,
        "industry": draft.industry,
        "geography": draft.geography,
        "problem": draft.problem,
        "target audience": draft.target_audience,
        "offer": draft.offer,
        "budget": draft.budget,
        "brand preferences": draft.brand_preferences,
    }
    missing = [label for label, value in required_scalars.items() if not value or not value.strip()]
    if draft.business_type not in {"idea", "existing"} and "business type" not in missing:
        missing.append("business type")
    if not draft.goals:
        missing.append("at least one goal")
    return missing


class OnboardingService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def get_state(self, context: AuthContext) -> OnboardingState:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            draft = await database.get(BusinessOnboardingDraft, business.id)
            approved = await database.get(ApprovedBusinessProfile, business.id)
            return OnboardingState(
                business=business,
                draft=draft,
                approved_profile=approved,
            )

    async def save_foundation(
        self,
        context: AuthContext,
        *,
        expected_revision: int,
        business_type: str,
        business_name: str,
        industry: str,
        geography: str,
    ) -> BusinessOnboardingDraft:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                draft = await self._editable_draft(
                    database, business, expected_revision=expected_revision
                )
                draft.business_type = business_type
                draft.business_name = business_name
                draft.industry = industry
                draft.geography = geography
                self._saved(draft, next_step=2)
            return draft

    async def save_market(
        self,
        context: AuthContext,
        *,
        expected_revision: int,
        problem: str,
        target_audience: str,
        offer: str,
    ) -> BusinessOnboardingDraft:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                draft = await self._editable_draft(
                    database, business, expected_revision=expected_revision
                )
                draft.problem = problem
                draft.target_audience = target_audience
                draft.offer = offer
                self._saved(draft, next_step=3)
            return draft

    async def save_execution(
        self,
        context: AuthContext,
        *,
        expected_revision: int,
        goals: list[str],
        existing_assets: list[str],
        constraints: list[str],
        budget: str,
    ) -> BusinessOnboardingDraft:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                draft = await self._editable_draft(
                    database, business, expected_revision=expected_revision
                )
                draft.goals = goals
                draft.existing_assets = existing_assets
                draft.constraints = constraints
                draft.budget = budget
                self._saved(draft, next_step=4)
            return draft

    async def save_brand_and_services(
        self,
        context: AuthContext,
        *,
        expected_revision: int,
        brand_preferences: str,
        connected_services: list[str],
    ) -> BusinessOnboardingDraft:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                draft = await self._editable_draft(
                    database, business, expected_revision=expected_revision
                )
                draft.brand_preferences = brand_preferences
                draft.connected_services = connected_services
                self._saved(draft, next_step=5)
            return draft

    async def submit_for_review(
        self, context: AuthContext, *, expected_revision: int
    ) -> BusinessOnboardingDraft:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context)
                draft = await self._editable_draft(
                    database,
                    business,
                    expected_revision=expected_revision,
                    create=False,
                )
                missing = missing_required_fields(draft)
                if missing:
                    raise OnboardingIncomplete(missing)
                draft.status = "review"
                draft.current_step = 5
                draft.submitted_at = _now()
                draft.updated_at = draft.submitted_at
                draft.revision += 1
            return draft

    async def approve(
        self, context: AuthContext, *, expected_revision: int
    ) -> ApprovedBusinessProfile:
        try:
            async with self._session_factory() as database:
                async with database.begin():
                    business = await resolve_selected_business(database, context, lock=True)
                    draft = await database.get(
                        BusinessOnboardingDraft, business.id, with_for_update=True
                    )
                    if draft is None or draft.status != "review":
                        raise OnboardingStateConflict
                    self._check_revision(draft, expected_revision)
                    missing = missing_required_fields(draft)
                    if missing:
                        raise OnboardingIncomplete(missing)
                    approved = await database.get(
                        ApprovedBusinessProfile, business.id, with_for_update=True
                    )
                    now = _now()
                    if approved is None:
                        approved = ApprovedBusinessProfile(
                            business_id=business.id,
                            version=1,
                            business_type=draft.business_type or "",
                            business_name=draft.business_name or "",
                            industry=draft.industry or "",
                            geography=draft.geography or "",
                            problem=draft.problem or "",
                            target_audience=draft.target_audience or "",
                            offer=draft.offer or "",
                            goals=list(draft.goals or []),
                            existing_assets=list(draft.existing_assets or []),
                            constraints=list(draft.constraints or []),
                            budget=draft.budget or "",
                            brand_preferences=draft.brand_preferences or "",
                            connected_services=list(draft.connected_services or []),
                            approved_by_owner_id=context.owner.id,
                            approved_at=now,
                        )
                        database.add(approved)
                    else:
                        approved.version += 1
                        approved.business_type = draft.business_type or ""
                        approved.business_name = draft.business_name or ""
                        approved.industry = draft.industry or ""
                        approved.geography = draft.geography or ""
                        approved.problem = draft.problem or ""
                        approved.target_audience = draft.target_audience or ""
                        approved.offer = draft.offer or ""
                        approved.goals = list(draft.goals or [])
                        approved.existing_assets = list(draft.existing_assets or [])
                        approved.constraints = list(draft.constraints or [])
                        approved.budget = draft.budget or ""
                        approved.brand_preferences = draft.brand_preferences or ""
                        approved.connected_services = list(draft.connected_services or [])
                        approved.approved_by_owner_id = context.owner.id
                        approved.approved_at = now
                    business.name = approved.business_name
                    business.updated_at = now
                    draft.status = "approved"
                    draft.updated_at = now
                    draft.revision += 1
                    await database.flush()
                return approved
        except IntegrityError as error:
            raise BusinessNameConflict from error

    async def reopen(
        self, context: AuthContext, *, expected_revision: int
    ) -> BusinessOnboardingDraft:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context)
                draft = await database.get(
                    BusinessOnboardingDraft, business.id, with_for_update=True
                )
                if draft is None or draft.status not in {"review", "approved"}:
                    raise OnboardingStateConflict
                self._check_revision(draft, expected_revision)
                draft.status = "draft"
                draft.submitted_at = None
                draft.updated_at = _now()
                draft.revision += 1
            return draft

    async def _editable_draft(
        self,
        database: AsyncSession,
        business: Business,
        *,
        expected_revision: int,
        create: bool = True,
    ) -> BusinessOnboardingDraft:
        draft = await database.get(BusinessOnboardingDraft, business.id, with_for_update=True)
        if draft is None:
            if not create or expected_revision != 0:
                raise OnboardingRevisionConflict
            now = _now()
            draft = BusinessOnboardingDraft(
                business_id=business.id,
                status="draft",
                current_step=1,
                revision=0,
                business_type=None,
                business_name=business.name,
                industry=None,
                geography=None,
                problem=None,
                target_audience=None,
                offer=None,
                goals=None,
                existing_assets=None,
                constraints=None,
                budget=None,
                brand_preferences=None,
                connected_services=None,
                created_at=now,
                updated_at=now,
                submitted_at=None,
            )
            database.add(draft)
        if draft.status != "draft":
            raise OnboardingStateConflict
        self._check_revision(draft, expected_revision)
        return draft

    @staticmethod
    def _check_revision(draft: BusinessOnboardingDraft, expected_revision: int) -> None:
        if draft.revision != expected_revision:
            raise OnboardingRevisionConflict

    @staticmethod
    def _saved(draft: BusinessOnboardingDraft, *, next_step: int) -> None:
        draft.current_step = max(draft.current_step, next_step)
        draft.revision += 1
        draft.updated_at = _now()
