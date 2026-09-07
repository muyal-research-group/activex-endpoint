from __future__ import annotations

from typing import Any, Dict, Optional

from option import Ok, Result
from xolo.client import XoloClient

from axo_vem.domain.errors import DomainError
from axo_vem.domain.events import models
from axo_vem.domain.events.publisher import EventPublisher
from axo_vem.domain.identity.user_profile import stream_name


class SignupUseCase:
    """Provisions the external Xolo identity, then maps the returned id to a
    local UserProfile via UserProfileCreated -- signup is the primary path a
    new UserProfile comes into existence through. Named exception to
    "application imports only domain" (see migration plan decision F):
    imports xolo.client.XoloClient directly rather than introducing an
    IdentityProvider ABC purely for layering purity.

    Replaces the body of the former POST /signup route handler
    (api/routes/user_profile.py).
    """

    def __init__(self, xolo_client: XoloClient, event_publisher: EventPublisher) -> None:
        self._xolo_client = xolo_client
        self._event_publisher = event_publisher

    def execute(
        self,
        *,
        username: str,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        scope: str,
        profile_photo: str,
        expiration: str,
        color: Optional[str],
        view_mode: str,
        language: str,
        activity_window_minutes: int = 60,
        endpoint_purge_eligible_after_minutes: int = 60,
    ) -> Result[Dict[str, Any], Any]:
        signup_result = self._xolo_client.signup(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=password,
            scope=scope,
            profile_photo=profile_photo,
            expiration=expiration,
        )
        if signup_result.is_err:
            return signup_result

        user_id = signup_result.unwrap().key
        preferences = models.Preferences(
            color=color, view_mode=view_mode, language=language,
            activity_window_minutes=activity_window_minutes,
            endpoint_purge_eligible_after_minutes=endpoint_purge_eligible_after_minutes,
        )
        event = models.UserProfileCreated(user_id=user_id, profile_photo=profile_photo, preferences=preferences)
        data = event.model_dump(mode="json")
        try:
            self._event_publisher.append_to_stream(stream_name(user_id), models.USER_PROFILE_CREATED, data)
        except Exception as exc:
            failure_event = models.UserProfileCreationFailed(
                user_id=user_id,
                failure=models.FailureDetail(
                    error_class=exc.__class__.__name__,
                    error_code=500,
                    component="identity.signup",
                    message=str(exc),
                ),
            )
            try:
                self._event_publisher.append_to_stream(
                    stream_name(user_id), models.USER_PROFILE_CREATION_FAILED, failure_event.model_dump(mode="json"),
                )
            except Exception:
                pass  # best-effort audit trail; the identity was still created upstream
            raise DomainError("signed up with Xolo but failed to create the local user profile") from exc
        return Ok(data)
