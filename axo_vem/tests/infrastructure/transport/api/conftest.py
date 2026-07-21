import mongomock
import pytest
from fastapi.testclient import TestClient
from option import Ok
from xolo.client.models import AuthenticatedDTO, CreatedUserResponseDTO, UserDTO

from axo_vem.application.compute.delete_function import DeleteFunctionUseCase
from axo_vem.application.compute.purge_function_version import PurgeFunctionVersionUseCase
from axo_vem.application.compute.register_function import RegisterFunctionUseCase
from axo_vem.application.compute.submit_function_job import SubmitFunctionJobUseCase
from axo_vem.application.compute.update_function import UpdateFunctionUseCase
from axo_vem.application.identity.create_profile import CreateProfileUseCase
from axo_vem.application.identity.delete_profile import DeleteProfileUseCase
from axo_vem.application.identity.signup import SignupUseCase
from axo_vem.application.identity.update_profile import UpdateProfileUseCase
from axo_vem.application.nodes.purge_endpoint import PurgeEndpointUseCase
from axo_vem.application.projector.dispatcher import apply_event
from axo_vem.application.projector.handlers import ProjectorHandlers
from axo_vem.application.workspace.create_virtual_environment import CreateVirtualEnvironmentUseCase
from axo_vem.application.workspace.delete_virtual_environment import DeleteVirtualEnvironmentUseCase
from axo_vem.application.workspace.purge_virtual_environment import PurgeVirtualEnvironmentUseCase
from axo_vem.application.workspace.update_virtual_environment import UpdateVirtualEnvironmentUseCase
from axo_vem.infrastructure.database.mongo.activity_repository import MongoActivityRepository
from axo_vem.infrastructure.database.mongo.bucket_repository import (
    MongoBucketRepository,
    MongoDataItemRepository,
)
from axo_vem.infrastructure.database.mongo.collections import ReadCollections
from axo_vem.infrastructure.database.mongo.consensus_repository import MongoConsensusRepository
from axo_vem.infrastructure.database.mongo.endpoint_repository import MongoEndpointRepository
from axo_vem.infrastructure.database.mongo.function_repository import MongoFunctionRepository
from axo_vem.infrastructure.database.mongo.job_repository import MongoJobRepository
from axo_vem.infrastructure.database.mongo.user_profile_repository import MongoUserProfileRepository
from axo_vem.infrastructure.database.mongo.virtual_environment_repository import (
    MongoVirtualEnvironmentRepository,
)
from axo_vem.infrastructure.transport.api.app import create_app


class _FakeKurrentReader:
    def __init__(self, streams=None):
        self._streams = streams or {}

    def get_stream(self, stream_name):
        if stream_name not in self._streams:
            raise KeyError(stream_name)
        return self._streams[stream_name]


class _FakeAppender:
    """Applies straight to the read model synchronously, standing in for the
    real Kurrent subscriber's async catch-up subscription so route tests
    don't need to poll/wait for eventual consistency."""

    def __init__(self, handlers):
        self._handlers = handlers
        self.appended = []

    def append_to_stream(self, stream_name, event_type, data):
        self.appended.append((stream_name, event_type, data))
        apply_event(self._handlers, event_type, data)


FAKE_USER = UserDTO(
    key="user-1", username="alice", first_name="Alice", last_name="A",
    email="alice@example.com", profile_photo="",
)


def _fake_current_user():
    return FAKE_USER


class _FakeXoloClient:
    """Stands in for xolo.client.XoloClient in route tests -- only signup
    and auth are exercised through HTTP (everything else goes through
    _fake_current_user, substituted directly as the dependency callable,
    never through real Authorization/Temporal-Secret-Key headers)."""

    def __init__(self):
        self.signup_calls = []
        self.auth_calls = []
        self.signup_result = Ok(CreatedUserResponseDTO(key=FAKE_USER.key))
        self.auth_result = Ok(AuthenticatedDTO(
            username=FAKE_USER.username, first_name=FAKE_USER.first_name, last_name=FAKE_USER.last_name,
            email=FAKE_USER.email, profile_photo=FAKE_USER.profile_photo,
            access_token="tok123", temporal_secret="sec456", user_id=FAKE_USER.key,
        ))

    def signup(self, **kwargs):
        self.signup_calls.append(kwargs)
        return self.signup_result

    def auth(self, **kwargs):
        self.auth_calls.append(kwargs)
        return self.auth_result


@pytest.fixture
def fake_xolo_client():
    return _FakeXoloClient()


@pytest.fixture
def db():
    return mongomock.MongoClient()["test"]


@pytest.fixture
def collections(db):
    return ReadCollections(endpoints=db["endpoints"], functions=db["functions"], consensus=db["consensus"])


@pytest.fixture
def activity_repository(db):
    return MongoActivityRepository(db["unified_activity"])


@pytest.fixture
def user_profile_repository(db):
    return MongoUserProfileRepository(db["user_profiles"])


@pytest.fixture
def virtual_environment_repository(db):
    return MongoVirtualEnvironmentRepository(db["virtual_environments"])


@pytest.fixture
def endpoint_repository(db):
    return MongoEndpointRepository(db["endpoints"])


@pytest.fixture
def function_repository(db):
    return MongoFunctionRepository(db["functions"])


@pytest.fixture
def consensus_repository(db):
    return MongoConsensusRepository(db["consensus"])


@pytest.fixture
def job_repository(db):
    return MongoJobRepository(db["jobs"])


@pytest.fixture
def bucket_repository(db):
    return MongoBucketRepository(db["buckets"])


@pytest.fixture
def data_item_repository(db):
    return MongoDataItemRepository(db["bucket_data"])


@pytest.fixture
def projector_handlers(
    activity_repository, user_profile_repository, virtual_environment_repository,
    endpoint_repository, function_repository, consensus_repository, job_repository,
    bucket_repository, data_item_repository,
):
    return ProjectorHandlers(
        activity_recorder=activity_repository,
        user_profile_repository=user_profile_repository,
        virtual_environment_repository=virtual_environment_repository,
        endpoint_repository=endpoint_repository,
        function_repository=function_repository,
        consensus_recorder=consensus_repository,
        job_repository=job_repository,
        bucket_repository=bucket_repository,
        data_item_repository=data_item_repository,
    )


@pytest.fixture
def kurrent_appender(projector_handlers):
    return _FakeAppender(projector_handlers)


@pytest.fixture
def fake_kurrent_reader():
    return _FakeKurrentReader()


@pytest.fixture
def signup_use_case(fake_xolo_client, kurrent_appender):
    return SignupUseCase(fake_xolo_client, kurrent_appender)


@pytest.fixture
def create_profile_use_case(user_profile_repository, kurrent_appender):
    return CreateProfileUseCase(user_profile_repository, kurrent_appender)


@pytest.fixture
def update_profile_use_case(user_profile_repository, kurrent_appender):
    return UpdateProfileUseCase(user_profile_repository, kurrent_appender)


@pytest.fixture
def delete_profile_use_case(user_profile_repository, kurrent_appender):
    return DeleteProfileUseCase(user_profile_repository, kurrent_appender)


@pytest.fixture
def create_virtual_environment_use_case(kurrent_appender):
    return CreateVirtualEnvironmentUseCase(kurrent_appender)


@pytest.fixture
def update_virtual_environment_use_case(virtual_environment_repository, kurrent_appender):
    return UpdateVirtualEnvironmentUseCase(virtual_environment_repository, kurrent_appender)


@pytest.fixture
def delete_virtual_environment_use_case(virtual_environment_repository, kurrent_appender, collections):
    return DeleteVirtualEnvironmentUseCase(virtual_environment_repository, kurrent_appender, collections.endpoints)


@pytest.fixture
def purge_virtual_environment_use_case(db, activity_repository):
    return PurgeVirtualEnvironmentUseCase(db["virtual_environments"], activity_repository)


@pytest.fixture
def register_function_use_case(virtual_environment_repository, endpoint_repository):
    return RegisterFunctionUseCase(virtual_environment_repository, endpoint_repository, 0.3)


@pytest.fixture
def delete_function_use_case(function_repository, endpoint_repository, job_repository):
    return DeleteFunctionUseCase(function_repository, endpoint_repository, job_repository, 0.3)


@pytest.fixture
def update_function_use_case(function_repository, endpoint_repository):
    return UpdateFunctionUseCase(function_repository, endpoint_repository, 0.3)


@pytest.fixture
def purge_function_version_use_case(db, activity_repository):
    return PurgeFunctionVersionUseCase(db["functions"], activity_repository)


@pytest.fixture
def submit_function_job_use_case(function_repository, virtual_environment_repository, endpoint_repository):
    return SubmitFunctionJobUseCase(function_repository, virtual_environment_repository, endpoint_repository, 0.3)


@pytest.fixture
def purge_endpoint_use_case(db, activity_repository, function_repository, job_repository, kurrent_appender):
    return PurgeEndpointUseCase(db["endpoints"], activity_repository, function_repository, job_repository, kurrent_appender)


@pytest.fixture
def client(
    collections, activity_repository, user_profile_repository, virtual_environment_repository, job_repository,
    bucket_repository, data_item_repository,
    signup_use_case, create_profile_use_case, update_profile_use_case, delete_profile_use_case,
    create_virtual_environment_use_case, update_virtual_environment_use_case, delete_virtual_environment_use_case,
    purge_virtual_environment_use_case,
    register_function_use_case, delete_function_use_case, update_function_use_case,
    purge_function_version_use_case, purge_endpoint_use_case, submit_function_job_use_case,
    fake_kurrent_reader, fake_xolo_client,
):
    app = create_app(
        collections=collections,
        activity_repository=activity_repository,
        user_profile_repository=user_profile_repository,
        virtual_environment_repository=virtual_environment_repository,
        job_repository=job_repository,
        bucket_repository=bucket_repository,
        data_item_repository=data_item_repository,
        signup_use_case=signup_use_case,
        create_profile_use_case=create_profile_use_case,
        update_profile_use_case=update_profile_use_case,
        delete_profile_use_case=delete_profile_use_case,
        create_virtual_environment_use_case=create_virtual_environment_use_case,
        update_virtual_environment_use_case=update_virtual_environment_use_case,
        delete_virtual_environment_use_case=delete_virtual_environment_use_case,
        purge_virtual_environment_use_case=purge_virtual_environment_use_case,
        register_function_use_case=register_function_use_case,
        delete_function_use_case=delete_function_use_case,
        update_function_use_case=update_function_use_case,
        purge_function_version_use_case=purge_function_version_use_case,
        submit_function_job_use_case=submit_function_job_use_case,
        purge_endpoint_use_case=purge_endpoint_use_case,
        kurrent_reader=fake_kurrent_reader,
        current_user_dependency=_fake_current_user,
        identity_dependency=_fake_current_user,
        xolo_client=fake_xolo_client,
        endpoint_command_timeout_seconds=0.3,
    )
    return TestClient(app)
