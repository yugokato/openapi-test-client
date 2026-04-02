from pathlib import Path

import pytest
from pact import Verifier

pytestmark = [pytest.mark.contracttest, pytest.mark.xdist_group("contract")]


def test_auth_provider(pacts_dir: Path, host: str, port: int, auth_provider_token: str) -> None:
    """Test the auth provider against the consumer contract"""
    verifier = (
        Verifier("auth-provider", host=host)
        .add_source(pacts_dir)
        .add_transport(url=f"http://{host}:{port}")
        .add_custom_header("Authorization", f"Bearer {auth_provider_token}")
    )
    verifier.verify()


def test_user_provider(pacts_dir: Path, host: str, port: int, token: str) -> None:
    """Test the users provider against the consumer contract"""
    verifier = (
        Verifier("user-provider", host=host)
        .add_source(pacts_dir)
        .add_transport(url=f"http://{host}:{port}")
        .add_custom_header("Authorization", f"Bearer {token}")
    )
    verifier.verify()
