"""
Tests for the DB layer.

Covers:
    - Migration runner: applies ``0001_init.sql``, idempotent on re-run.
    - Profile: get returns the seeded singleton; set/set_many update fields;
      JSON fields round-trip native Python lists; unknown fields raise.
    - Items: add/get/list/update/soft_delete/restore; default queries hide
      soft-deleted rows; JSON fields round-trip.
    - Vector search: set_embedding stores 512-dim vector; find_similar
      returns nearest items, excludes soft-deleted, respects exclude_ids.

All tests use a tmp_path SQLite file to exercise sqlite-vec for real;
in-memory ":memory:" works too but file-backed catches WAL pragma issues.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawbot.db import Repo, connect, run_migrations
from clawbot.db.repo import WardrobeItem

# Path to the migrations dir, resolved relative to this test file.
MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent / "src" / "clawbot" / "db" / "migrations"
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Fresh empty DB file. Each test gets its own."""
    return tmp_path / "clawbot_test.db"


@pytest.fixture
def repo(db_path: Path) -> Repo:
    """Connection + migrated schema, ready for use."""
    conn = connect(db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    return Repo(conn)


# ─────────────────────────────────────────────────────────────────────────────
# Migrations
# ─────────────────────────────────────────────────────────────────────────────


def test_migrations_apply_to_empty_db(db_path: Path) -> None:
    conn = connect(db_path)
    applied = run_migrations(conn, MIGRATIONS_DIR)
    assert applied == [1]

    # Re-running is a no-op.
    again = run_migrations(conn, MIGRATIONS_DIR)
    assert again == []


def test_migrations_seed_profile_singleton(repo: Repo) -> None:
    profile = repo.profile.get()
    # The migration inserts the placeholder row with id=1.
    assert profile["id"] == 1
    # All other fields default to None.
    assert profile["skin_undertone"] is None


def test_vec_table_exists(repo: Repo) -> None:
    """sqlite-vec must have created the vec0 virtual table."""
    rows = repo.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='wardrobe_items_vec'"
    ).fetchall()
    assert len(rows) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────────────────────────────────────


def test_profile_set_and_get_scalar(repo: Repo) -> None:
    repo.profile.set("skin_undertone", "warm")
    repo.profile.set("comfort_vs_style", 7)
    profile = repo.profile.get()
    assert profile["skin_undertone"] == "warm"
    assert profile["comfort_vs_style"] == 7


def test_profile_set_json_field_serializes(repo: Repo) -> None:
    """Passing a Python list to a *_json field stores it as JSON text."""
    repo.profile.set("favorite_colors_json", ["navy", "camel", "burgundy"])
    profile = repo.profile.get()
    assert profile["favorite_colors_json"] == ["navy", "camel", "burgundy"]


def test_profile_set_many_atomic(repo: Repo) -> None:
    repo.profile.set_many({
        "skin_undertone": "cool",
        "favorite_colors_json": ["forest", "rust"],
        "comfort_vs_style": 5,
    })
    p = repo.profile.get()
    assert p["skin_undertone"] == "cool"
    assert p["favorite_colors_json"] == ["forest", "rust"]
    assert p["comfort_vs_style"] == 5


def test_profile_unknown_field_rejected(repo: Repo) -> None:
    with pytest.raises(KeyError, match="favorite_pet"):
        repo.profile.set("favorite_pet", "cat")
    with pytest.raises(KeyError):
        repo.profile.set_many({"name": "Fidel", "made_up": "x"})


# ─────────────────────────────────────────────────────────────────────────────
# Items: CRUD round-trip
# ─────────────────────────────────────────────────────────────────────────────


def _sample_cardigan() -> WardrobeItem:
    return WardrobeItem(
        category="tops",
        subcategory="cardigan",
        brand="COS",
        name="oatmeal merino cardigan",
        color_primary="oatmeal",
        pattern="solid",
        fabric=["merino", "wool"],
        fit="relaxed",
        formality="smart-casual",
        seasons=["fall", "winter", "spring"],
        size_on_tag="M",
        size_true="M",
        purchase_date="2025-09-01",
        purchase_price_usd=129.0,
        purchased_from="cos.com",
        condition="good",
        care="hand-wash",
        pairs_well_with=["item-A", "item-B"],
        notes="Goes with dark trousers.",
    )


def test_item_add_assigns_id(repo: Repo) -> None:
    item = _sample_cardigan()
    new_id = repo.items.add(item)
    assert isinstance(new_id, str) and len(new_id) >= 32
    assert item.id == new_id


def test_item_get_round_trips_json(repo: Repo) -> None:
    item = _sample_cardigan()
    item_id = repo.items.add(item)
    fetched = repo.items.get(item_id)
    assert fetched is not None
    assert fetched.subcategory == "cardigan"
    assert fetched.fabric == ["merino", "wool"]
    assert fetched.seasons == ["fall", "winter", "spring"]
    assert fetched.pairs_well_with == ["item-A", "item-B"]
    assert fetched.needs_tailoring is False


def test_item_list_filters_by_category(repo: Repo) -> None:
    repo.items.add(_sample_cardigan())
    repo.items.add(WardrobeItem(category="bottoms", subcategory="jeans", color_primary="indigo"))
    tops = repo.items.list_by_category("tops")
    bottoms = repo.items.list_by_category("bottoms")
    assert len(tops) == 1 and tops[0].subcategory == "cardigan"
    assert len(bottoms) == 1 and bottoms[0].subcategory == "jeans"
    # No filter returns both
    assert repo.items.count() == 2


def test_item_update_partial(repo: Repo) -> None:
    item_id = repo.items.add(_sample_cardigan())
    repo.items.update(item_id, wear_count=3, last_worn_date="2025-10-15")
    fetched = repo.items.get(item_id)
    assert fetched is not None
    assert fetched.wear_count == 3
    assert fetched.last_worn_date == "2025-10-15"


def test_item_update_unknown_field_rejected(repo: Repo) -> None:
    item_id = repo.items.add(_sample_cardigan())
    with pytest.raises(KeyError, match="invented_field"):
        repo.items.update(item_id, invented_field="oops")


# ─────────────────────────────────────────────────────────────────────────────
# Items: soft delete
# ─────────────────────────────────────────────────────────────────────────────


def test_soft_delete_hides_from_default_queries(repo: Repo) -> None:
    item_id = repo.items.add(_sample_cardigan())
    repo.items.soft_delete(item_id)

    # Default get excludes deleted
    assert repo.items.get(item_id) is None
    # include_deleted reveals it
    found = repo.items.get(item_id, include_deleted=True)
    assert found is not None and found.deleted_at is not None
    # Lists exclude deleted by default
    assert repo.items.count() == 0
    assert repo.items.count(include_deleted=True) == 1


def test_restore_undoes_soft_delete(repo: Repo) -> None:
    item_id = repo.items.add(_sample_cardigan())
    repo.items.soft_delete(item_id)
    repo.items.restore(item_id)
    fetched = repo.items.get(item_id)
    assert fetched is not None
    assert fetched.deleted_at is None


# ─────────────────────────────────────────────────────────────────────────────
# Vector search
# ─────────────────────────────────────────────────────────────────────────────


def _vec(seed: float) -> list[float]:
    """Deterministic 512-dim vector for tests; first slot is the seed."""
    v = [0.0] * 512
    v[0] = seed
    v[1] = 1.0  # constant tail so vectors aren't degenerate
    return v


def test_set_embedding_validates_length(repo: Repo) -> None:
    item_id = repo.items.add(_sample_cardigan())
    with pytest.raises(ValueError, match="512-dim"):
        repo.items.set_embedding(item_id, [0.1, 0.2, 0.3])


def test_find_similar_returns_nearest_first(repo: Repo) -> None:
    a_id = repo.items.add(WardrobeItem(category="tops", subcategory="t-shirt"))
    b_id = repo.items.add(WardrobeItem(category="tops", subcategory="blouse"))
    c_id = repo.items.add(WardrobeItem(category="tops", subcategory="cardigan"))

    repo.items.set_embedding(a_id, _vec(0.0))
    repo.items.set_embedding(b_id, _vec(0.5))
    repo.items.set_embedding(c_id, _vec(1.0))

    # Query close to A → A first.
    results = repo.items.find_similar(_vec(0.05), k=3)
    ids = [item_id for item_id, _dist in results]
    assert ids[0] == a_id
    # All three should be present.
    assert set(ids) == {a_id, b_id, c_id}


def test_find_similar_excludes_deleted(repo: Repo) -> None:
    a_id = repo.items.add(WardrobeItem(category="tops"))
    b_id = repo.items.add(WardrobeItem(category="tops"))
    repo.items.set_embedding(a_id, _vec(0.0))
    repo.items.set_embedding(b_id, _vec(0.5))
    repo.items.soft_delete(a_id)

    results = repo.items.find_similar(_vec(0.0), k=5)
    ids = [r[0] for r in results]
    assert a_id not in ids
    assert b_id in ids


def test_find_similar_respects_exclude_ids(repo: Repo) -> None:
    ids = [
        repo.items.add(WardrobeItem(category="tops", subcategory=f"sub{i}"))
        for i in range(3)
    ]
    for i, item_id in enumerate(ids):
        repo.items.set_embedding(item_id, _vec(i * 0.1))

    results = repo.items.find_similar(_vec(0.0), k=5, exclude_ids=[ids[0]])
    found = [r[0] for r in results]
    assert ids[0] not in found
