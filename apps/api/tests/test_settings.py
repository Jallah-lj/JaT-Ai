"""Contract tests for the settings boundary that do not require a database."""

import pytest
from pydantic import ValidationError

from jat_api.config import Settings
from jat_api.settings.schemas import (
    MAX_MEMORIES,
    AccountDeletion,
    MemoryCreate,
    PasswordChange,
    Preferences,
    PreferencesUpdate,
    ProfileUpdate,
)


def test_preferences_default_to_a_complete_safe_document() -> None:
    preferences = Preferences()
    assert preferences.theme == "system"
    assert preferences.accent == "evergreen"
    assert preferences.memories == []
    # Privacy-affecting options must default to off.
    assert preferences.analytics_enabled is False
    assert preferences.email_product_updates is False


def test_preferences_ignore_unknown_stored_keys_so_old_rows_still_load() -> None:
    preferences = Preferences.model_validate(
        {"theme": "dark", "legacy_field": "value", "is_admin": True}
    )
    assert preferences.theme == "dark"
    assert not hasattr(preferences, "is_admin")


def test_partial_update_only_reports_supplied_fields() -> None:
    patch = PreferencesUpdate.model_validate({"theme": "dark"})
    assert patch.model_dump(exclude_unset=True) == {"theme": "dark"}


def test_partial_update_merges_onto_existing_document() -> None:
    current = Preferences(theme="dark", accent="ocean", temperature=1.5)
    patch = PreferencesUpdate.model_validate({"temperature": 0.4})
    changes = patch.model_dump(exclude_unset=True, exclude_none=True)
    merged = Preferences.model_validate({**current.model_dump(mode="json"), **changes})
    assert merged.temperature == 0.4
    assert merged.theme == "dark"
    assert merged.accent == "ocean"


def test_update_rejects_unknown_fields_to_prevent_privilege_smuggling() -> None:
    with pytest.raises(ValidationError):
        PreferencesUpdate.model_validate({"is_admin": True})


@pytest.mark.parametrize(
    "payload",
    [
        {"theme": "neon"},
        {"accent": "rainbow"},
        {"font_scale": "enormous"},
        {"density": "airy"},
        {"temperature": 2.5},
        {"temperature": -0.1},
        {"max_tokens": 1},
        {"max_tokens": 999_999},
        {"default_model": ""},
    ],
)
def test_update_rejects_out_of_range_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PreferencesUpdate.model_validate(payload)


def test_memory_list_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Preferences(memories=[f"memory {index}" for index in range(MAX_MEMORIES + 1)])


def test_memory_text_is_bounded_and_non_empty() -> None:
    assert MemoryCreate(text="Prefers concise answers").text
    with pytest.raises(ValidationError):
        MemoryCreate(text="")
    with pytest.raises(ValidationError):
        MemoryCreate(text="x" * 501)


def test_password_change_enforces_minimum_length() -> None:
    with pytest.raises(ValidationError):
        PasswordChange(current_password="old", new_password="short")
    assert PasswordChange(current_password="old", new_password="long-enough")


def test_profile_update_validates_email_and_name_bounds() -> None:
    assert ProfileUpdate(display_name="Ada", email="ada@example.com")
    with pytest.raises(ValidationError):
        ProfileUpdate(email="not-an-email")
    with pytest.raises(ValidationError):
        ProfileUpdate(display_name="")


def test_account_deletion_requires_password_and_confirmation() -> None:
    assert AccountDeletion(password="secret", confirmation="DELETE")
    with pytest.raises(ValidationError):
        AccountDeletion(password="", confirmation="DELETE")


def test_system_prompt_is_length_limited() -> None:
    with pytest.raises(ValidationError):
        PreferencesUpdate(system_prompt="x" * 4001)


def test_cors_origins_accept_comma_separated_and_json_forms() -> None:
    """.env.example documents the comma-separated form; both must load."""
    comma = Settings(environment="testing", cors_origins="http://a.test,http://b.test")
    assert comma.cors_origins == ["http://a.test", "http://b.test"]
    json_form = Settings(environment="testing", cors_origins='["http://c.test"]')
    assert json_form.cors_origins == ["http://c.test"]


def test_model_endpoint_rejects_markdown_link_formatting() -> None:
    with pytest.raises(ValidationError, match="plain http"):
        Settings(model_endpoint="[http://127.0.0.1:11434](http://127.0.0.1:11434)")


def test_cors_origins_reject_markdown_link_formatting() -> None:
    with pytest.raises(ValidationError, match="plain http"):
        Settings(cors_origins='["[http://localhost:5173](http://localhost:5173)"]')


def test_ollama_requires_an_endpoint() -> None:
    with pytest.raises(ValidationError, match="JAT_MODEL_ENDPOINT is required"):
        Settings(model_provider="ollama", model_endpoint=None)


def test_chat_title_helper_truncates_cleanly() -> None:
    from jat_api.chat import title_from_content

    assert title_from_content("  Hello   world  ") == "Hello world"
    assert title_from_content("") == "New conversation"
    long = "word " * 40
    titled = title_from_content(long, max_length=40)
    assert titled.endswith("…")
    assert len(titled) <= 40
