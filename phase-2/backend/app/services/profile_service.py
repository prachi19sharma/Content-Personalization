"""Global, domain and agent profile management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.catalog import get_agent_spec, get_domain
from app.agents.definitions import PRIMARY_DOMAIN
from app.core.logging import get_logger
from app.models.profiles import AgentProfile, DomainProfile, GlobalProfile
from app.models.user import User

logger = get_logger(__name__)

_ALLOWED_GLOBAL_FIELDS = {
    "display_name",
    "occupation",
    "location",
    "language",
    "preferred_response_length",
    "communication_style",
    "general_skill_level",
    "interests",
    "goals",
    "preferences",
    "bio",
}

_HISTORY_KEY = "history"


class ProfileService:
    # ------------------------------------------------------------- global
    def get_or_create_global_profile(self, db: Session, user: User) -> GlobalProfile:
        profile = db.scalar(select(GlobalProfile).where(GlobalProfile.user_id == user.id))
        if profile is None:
            profile = GlobalProfile(
                user_id=user.id,
                display_name=user.name,
                interests=[],
                goals=[],
                preferences={},
                personalization_version=1,
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)
            logger.info("Created global profile for %s", user.id)
        return profile

    def update_global_profile(
        self, db: Session, user: User, payload: dict[str, Any]
    ) -> GlobalProfile:
        profile = self.get_or_create_global_profile(db, user)
        for key, value in payload.items():
            if key in _ALLOWED_GLOBAL_FIELDS:
                setattr(profile, key, value)
        profile.personalization_version = (profile.personalization_version or 1) + 1
        db.commit()
        db.refresh(profile)
        return profile

    def apply_learned_global_preference(
        self, db: Session, user_id: uuid.UUID, key: str, value: Any
    ) -> bool:
        profile = db.scalar(select(GlobalProfile).where(GlobalProfile.user_id == user_id))
        if profile is None or key not in _ALLOWED_GLOBAL_FIELDS:
            return False
        if getattr(profile, key, None) == value:
            return False
        setattr(profile, key, value)
        profile.personalization_version = (profile.personalization_version or 1) + 1
        db.flush()
        logger.info("Global profile adapted: %s -> %r", key, value)
        return True

    # -------------------------------------------------------------- brands
    #
    # A "domain profile" is one brand. An account may hold many per domain and
    # works in one at a time, marked by ``is_active``. Everything below that
    # takes an optional ``brand_id`` falls back to the active brand, so callers
    # that do not care about brands keep working unchanged and still get
    # brand-correct answers.

    def list_brands(
        self, db: Session, user_id: uuid.UUID, domain_key: str
    ) -> list[DomainProfile]:
        spec = get_domain(domain_key)
        rows = db.scalars(
            select(DomainProfile)
            .where(DomainProfile.user_id == user_id, DomainProfile.domain == spec.key)
            .order_by(DomainProfile.created_at)
        ).all()
        return list(rows)

    def get_brand(
        self, db: Session, user_id: uuid.UUID, brand_id: uuid.UUID
    ) -> DomainProfile | None:
        """Tenant-scoped by design: another account's brand reads as missing."""
        return db.scalar(
            select(DomainProfile).where(
                DomainProfile.id == brand_id, DomainProfile.user_id == user_id
            )
        )

    def active_brand(
        self, db: Session, user_id: uuid.UUID, domain_key: str
    ) -> DomainProfile | None:
        """The brand this account is working in, self-healing.

        If no row is flagged -- possible after deleting the active brand -- the
        oldest remaining one is promoted rather than returning None, because
        "no active brand but brands exist" would strand the user in an empty UI.
        """
        spec = get_domain(domain_key)
        found = db.scalar(
            select(DomainProfile).where(
                DomainProfile.user_id == user_id,
                DomainProfile.domain == spec.key,
                DomainProfile.is_active.is_(True),
            )
        )
        if found is not None:
            return found

        brands = self.list_brands(db, user_id, spec.key)
        if not brands:
            return None
        promoted = brands[0]
        promoted.is_active = True
        db.commit()
        db.refresh(promoted)
        logger.info("No active brand for %s; promoted %s", user_id, promoted.id)
        return promoted

    def resolve_brand(
        self,
        db: Session,
        user_id: uuid.UUID,
        domain_key: str,
        brand_id: uuid.UUID | None = None,
    ) -> DomainProfile | None:
        """``brand_id`` when given and owned, otherwise the active brand."""
        if brand_id is not None:
            return self.get_brand(db, user_id, brand_id)
        return self.active_brand(db, user_id, domain_key)

    def create_brand(
        self,
        db: Session,
        user_id: uuid.UUID,
        domain_key: str,
        label: str = "",
        profile_data: dict[str, Any] | None = None,
        *,
        activate: bool = True,
    ) -> DomainProfile:
        spec = get_domain(domain_key)
        cleaned = self._sanitize(spec.profile_fields, profile_data or {})
        name = (label or str(cleaned.get("brand_name") or "")).strip() or "New brand"

        profile = DomainProfile(
            user_id=user_id,
            domain=spec.key,
            label=name[:160],
            profile_data=cleaned,
            revision=1,
            is_active=False,
        )
        profile.is_configured = self._is_configured(spec.profile_fields, cleaned)
        db.add(profile)
        db.commit()
        db.refresh(profile)
        logger.info("Created brand %r (%s) for %s", name, profile.id, user_id)

        # The first brand must end up active, or the account has none.
        if activate or len(self.list_brands(db, user_id, spec.key)) == 1:
            self.activate_brand(db, user_id, profile.id)
            db.refresh(profile)
        return profile

    def activate_brand(
        self, db: Session, user_id: uuid.UUID, brand_id: uuid.UUID
    ) -> DomainProfile | None:
        brand = self.get_brand(db, user_id, brand_id)
        if brand is None:
            return None
        for other in self.list_brands(db, user_id, brand.domain):
            other.is_active = other.id == brand.id
        db.commit()
        db.refresh(brand)
        logger.info("Active brand for %s -> %r (%s)", user_id, brand.label, brand.id)
        return brand

    def rename_brand(
        self, db: Session, user_id: uuid.UUID, brand_id: uuid.UUID, label: str
    ) -> DomainProfile | None:
        brand = self.get_brand(db, user_id, brand_id)
        if brand is None:
            return None
        brand.label = (label or "").strip()[:160] or brand.label
        db.commit()
        db.refresh(brand)
        return brand

    def delete_brand(self, db: Session, user_id: uuid.UUID, brand_id: uuid.UUID) -> bool:
        """Delete a brand and, by cascade, its agent profiles, chats and memories.

        Refuses to remove the last brand: the app has no coherent state without
        one, and the user almost certainly meant "clear it", not "delete it".
        """
        brand = self.get_brand(db, user_id, brand_id)
        if brand is None:
            return False
        siblings = self.list_brands(db, user_id, brand.domain)
        if len(siblings) <= 1:
            raise ValueError("This is your only brand — edit it instead of deleting it.")

        was_active = brand.is_active
        db.delete(brand)
        db.commit()
        if was_active:
            self.active_brand(db, user_id, brand.domain)  # promotes a survivor
        logger.info("Deleted brand %s for %s", brand_id, user_id)
        return True

    # ------------------------------------------------------------- domain
    def get_domain_profile(
        self, db: Session, user_id: uuid.UUID, domain_key: str
    ) -> DomainProfile | None:
        """The brand currently in use. Kept under the old name so the graph,
        catalog and personalization layers need no change to become
        brand-aware."""
        return self.active_brand(db, user_id, domain_key)

    def list_domain_profiles(self, db: Session, user_id: uuid.UUID) -> dict[str, DomainProfile]:
        """Active brand per domain, which is what the overview and stats mean."""
        rows = db.scalars(
            select(DomainProfile).where(
                DomainProfile.user_id == user_id, DomainProfile.is_active.is_(True)
            )
        ).all()
        return {row.domain: row for row in rows}

    def save_domain_profile(
        self,
        db: Session,
        user_id: uuid.UUID,
        domain_key: str,
        profile_data: dict[str, Any],
        brand_id: uuid.UUID | None = None,
    ) -> DomainProfile:
        spec = get_domain(domain_key)
        cleaned = self._sanitize(spec.profile_fields, profile_data)

        profile = self.resolve_brand(db, user_id, spec.key, brand_id)
        if profile is None:
            return self.create_brand(db, user_id, spec.key, profile_data=cleaned)

        merged = dict(profile.profile_data or {})
        merged.update(cleaned)
        profile.profile_data = merged
        profile.revision = (profile.revision or 1) + 1
        # Keep the switcher label in step with the answer while it is still the
        # default, but never overwrite a label the user set deliberately.
        brand_name = str(merged.get("brand_name") or "").strip()
        if brand_name and profile.label in ("", "New brand", "My brand"):
            profile.label = brand_name[:160]

        profile.is_configured = self._is_configured(spec.profile_fields, profile.profile_data)
        db.commit()
        db.refresh(profile)
        logger.info(
            "Saved brand %r (%s) configured=%s", profile.label, profile.id, profile.is_configured
        )
        return profile

    # -------------------------------------------------------------- agent
    def get_agent_profile(
        self,
        db: Session,
        user_id: uuid.UUID,
        agent_key: str,
        brand_id: uuid.UUID | None = None,
    ) -> AgentProfile | None:
        """This agent's answers *for one brand*.

        Without the brand filter the same agent would return whichever client's
        configuration happened to be stored first, which is the bug this whole
        change exists to remove.
        """
        spec = get_agent_spec(agent_key)
        brand = self.resolve_brand(db, user_id, spec.domain, brand_id)
        return db.scalar(
            select(AgentProfile).where(
                AgentProfile.user_id == user_id,
                AgentProfile.agent_key == spec.key,
                AgentProfile.brand_profile_id == (brand.id if brand else None),
            )
        )

    def list_agent_profiles(
        self, db: Session, user_id: uuid.UUID, brand_id: uuid.UUID | None = None
    ) -> dict[str, AgentProfile]:
        """Agent profiles for one brand, keyed by agent."""
        query = select(AgentProfile).where(AgentProfile.user_id == user_id)
        brand = (
            self.get_brand(db, user_id, brand_id)
            if brand_id is not None
            else self.active_brand(db, user_id, PRIMARY_DOMAIN)
        )
        query = query.where(AgentProfile.brand_profile_id == (brand.id if brand else None))
        rows = db.scalars(query).all()
        return {row.agent_key: row for row in rows}

    def save_agent_profile(
        self,
        db: Session,
        user_id: uuid.UUID,
        agent_key: str,
        profile_data: dict[str, Any],
        *,
        merge: bool = False,
        brand_id: uuid.UUID | None = None,
    ) -> AgentProfile:
        spec = get_agent_spec(agent_key)
        cleaned = self._sanitize(spec.profile_fields, profile_data)

        brand = self.resolve_brand(db, user_id, spec.domain, brand_id)
        if brand is None:
            # Configuring an agent before any brand exists: make one rather than
            # writing a brand-less row that no switcher can ever reach.
            brand = self.create_brand(db, user_id, spec.domain)

        profile = self.get_agent_profile(db, user_id, spec.key, brand.id)
        if profile is None:
            cleaned.setdefault(_HISTORY_KEY, [])
            profile = AgentProfile(
                user_id=user_id,
                brand_profile_id=brand.id,
                agent_key=spec.key,
                domain=spec.domain,
                profile_data=cleaned,
                interaction_count=0,
                revision=1,
            )
            db.add(profile)
        else:
            data = dict(profile.profile_data or {}) if merge else {}
            data.update(cleaned)
            data.setdefault(_HISTORY_KEY, (profile.profile_data or {}).get(_HISTORY_KEY, []))
            profile.profile_data = data
            profile.revision = (profile.revision or 1) + 1

        profile.is_configured = self._is_configured(spec.profile_fields, profile.profile_data)
        db.commit()
        db.refresh(profile)
        logger.info("Saved %s profile (configured=%s)", spec.key, profile.is_configured)
        return profile

    def ensure_agent_profile(
        self,
        db: Session,
        user_id: uuid.UUID,
        agent_key: str,
        brand_id: uuid.UUID | None = None,
    ) -> AgentProfile:
        """Return the profile, creating an unconfigured placeholder if needed, so a
        conversation can start before setup is completed."""
        spec = get_agent_spec(agent_key)
        brand = self.resolve_brand(db, user_id, spec.domain, brand_id)
        if brand is None:
            brand = self.create_brand(db, user_id, spec.domain)

        profile = self.get_agent_profile(db, user_id, agent_key, brand.id)
        if profile is not None:
            return profile
        profile = AgentProfile(
            user_id=user_id,
            brand_profile_id=brand.id,
            agent_key=spec.key,
            domain=spec.domain,
            profile_data=spec.default_profile(),
            is_configured=False,
            interaction_count=0,
            revision=1,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile

    def record_interaction(
        self, db: Session, profile: AgentProfile, topic: str | None = None
    ) -> None:
        profile.interaction_count = (profile.interaction_count or 0) + 1
        profile.last_used_at = datetime.now(UTC)
        if topic:
            data = dict(profile.profile_data or {})
            history = list(data.get(_HISTORY_KEY) or [])
            entry = topic.strip()[:120]
            if entry and (not history or history[-1] != entry):
                history.append(entry)
            data[_HISTORY_KEY] = history[-20:]
            profile.profile_data = data
        db.flush()

    def apply_learned_agent_preference(
        self, db: Session, profile: AgentProfile, key: str, value: Any
    ) -> bool:
        spec = get_agent_spec(profile.agent_key)
        if key not in {field.key for field in spec.profile_fields}:
            return False
        data = dict(profile.profile_data or {})
        if data.get(key) == value:
            return False
        data[key] = value
        profile.profile_data = data
        profile.revision = (profile.revision or 1) + 1
        db.flush()
        logger.info("Agent profile adapted: %s.%s -> %r", profile.agent_key, key, value)
        return True

    # ------------------------------------------------------------- status
    def missing_required(
        self, fields: tuple, profile_data: dict[str, Any] | None
    ) -> list[str]:
        data = profile_data or {}
        return [
            field.key
            for field in fields
            if field.required and data.get(field.key) in (None, "", [], {})
        ]

    def agent_status(
        self,
        db: Session,
        user_id: uuid.UUID,
        agent_key: str,
        brand_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Everything the UI needs to decide setup-vs-chat for one agent.

        Brand-scoped: the same agent is "Personalized" for one brand and
        "Not configured" for another, which is the whole point.
        """
        spec = get_agent_spec(agent_key)
        domain = get_domain(spec.domain)
        brand = self.resolve_brand(db, user_id, spec.domain, brand_id)
        agent_profile = self.get_agent_profile(db, user_id, spec.key, brand.id if brand else None)
        domain_profile = brand

        agent_data = agent_profile.profile_data if agent_profile else None
        domain_data = domain_profile.profile_data if domain_profile else None
        agent_missing = self.missing_required(spec.profile_fields, agent_data)
        domain_missing = self.missing_required(domain.profile_fields, domain_data)

        agent_ok = bool(agent_profile and agent_profile.is_configured)
        domain_ok = bool(domain_profile and domain_profile.is_configured)
        return {
            "agent_key": spec.key,
            "domain": spec.domain,
            "agent_exists": agent_profile is not None,
            "agent_configured": agent_ok,
            "domain_exists": domain_profile is not None,
            "domain_configured": domain_ok,
            "needs_setup": not (agent_ok and domain_ok),
            "missing_agent_fields": agent_missing,
            "missing_domain_fields": domain_missing,
            "status_label": "Personalized" if agent_ok and domain_ok else "Not configured",
            #: Which brand this status describes, so the UI can show it and
            #: refetch when the user switches.
            "brand_id": str(brand.id) if brand else None,
            "brand_label": brand.label if brand else None,
        }

    # ---------------------------------------------------------- internals
    def _sanitize(self, fields: tuple, payload: dict[str, Any]) -> dict[str, Any]:
        """Drop unknown keys and coerce values to the declared field kind."""
        allowed = {field.key: field for field in fields}
        cleaned: dict[str, Any] = {}
        for key, value in (payload or {}).items():
            if key == _HISTORY_KEY:
                if isinstance(value, list):
                    cleaned[key] = [str(item)[:160] for item in value][-20:]
                continue
            field = allowed.get(key)
            if field is None:
                continue
            cleaned[key] = self._coerce(field, value)
        return cleaned

    @staticmethod
    def _coerce(field: Any, value: Any) -> Any:
        if field.kind in ("multiselect", "tags"):
            if value is None:
                return []
            if isinstance(value, str):
                items = [part.strip() for part in value.split(",")]
            elif isinstance(value, (list, tuple, set)):
                items = [str(item).strip() for item in value]
            else:
                items = [str(value).strip()]
            unique: list[str] = []
            for item in items:
                if item and item not in unique:
                    unique.append(item[:120])
            return unique[:30]
        if field.kind == "number":
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        if value is None:
            return ""
        text = str(value).strip()
        return text[: 4000 if field.kind == "textarea" else 400]

    @staticmethod
    def _is_configured(fields: tuple, data: dict[str, Any]) -> bool:
        required = [field.key for field in fields if field.required]
        if required:
            return all(data.get(key) not in (None, "", [], {}) for key in required)
        return any(
            value not in (None, "", [], {})
            for key, value in (data or {}).items()
            if key != _HISTORY_KEY
        )


_service: ProfileService | None = None


def get_profile_service() -> ProfileService:
    global _service
    if _service is None:
        _service = ProfileService()
    return _service
