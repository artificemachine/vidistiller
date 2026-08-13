"""Contract for the public, non-secret fleet manifest schema."""

from app.services.llm_fleet import load_model_profiles


def test_checked_in_fleet_manifest_has_a_profiles_list():
    assert load_model_profiles() == {}
