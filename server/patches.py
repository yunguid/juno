"""Patch database management for MONTAGE M sounds"""
import json
from pathlib import Path
from .models import Patch, PatchCategory, SoundType
from .logger import get_logger

log = get_logger("patches")

# Category recommendations by sound type
SOUND_TYPE_CATEGORIES = {
    SoundType.BASS: ["Synth Bass", "Acoustic Bass"],
    SoundType.PAD: ["Pad", "Strings", "Brass", "Choir"],
    SoundType.LEAD: ["Synth Lead", "Keys", "Organ", "Pluck"],
}

# Cache for loaded patches
_patches: list[Patch] = []
_categories: list[PatchCategory] = []


def _get_data_path() -> Path:
    """Get path to the data directory"""
    return Path(__file__).parent / "data"


def load_patches() -> None:
    """Load patches from JSON file"""
    global _patches, _categories

    data_path = _get_data_path() / "patches.json"

    if not data_path.exists():
        log.warning(f"Patches file not found: {data_path}")
        _patches = []
        _categories = []
        return

    try:
        with open(data_path, "r") as f:
            data = json.load(f)

        _patches = [Patch(**p) for p in data.get("patches", [])]
        _categories = [PatchCategory(**c) for c in data.get("categories", [])]

        log.info(f"Loaded {len(_patches)} patches in {len(_categories)} categories")
    except Exception as e:
        log.error(f"Failed to load patches: {e}")
        _patches = []
        _categories = []


def get_patches(
    category: str | None = None,
    search: str | None = None,
    sound_type: SoundType | None = None,
    limit: int = 50,
    offset: int = 0
) -> tuple[list[Patch], int]:
    """
    Get patches with optional filtering.
    Returns (patches, total_count)
    """
    if not _patches:
        load_patches()

    filtered = _patches

    # Filter by category
    if category:
        filtered = [p for p in filtered if p.category.lower() == category.lower()]

    # Filter by sound type (recommended categories)
    if sound_type and sound_type in SOUND_TYPE_CATEGORIES:
        recommended = SOUND_TYPE_CATEGORIES[sound_type]
        filtered = [p for p in filtered if p.category in recommended]

    # Filter by search term
    if search:
        search_lower = search.lower()
        filtered = [
            p for p in filtered
            if search_lower in p.name.lower()
            or search_lower in p.category.lower()
            or any(search_lower in tag.lower() for tag in p.tags)
        ]

    total = len(filtered)

    # Apply pagination
    filtered = filtered[offset:offset + limit]

    return filtered, total


def get_patch_by_id(patch_id: str) -> Patch | None:
    """Get a single patch by ID"""
    if not _patches:
        load_patches()

    for patch in _patches:
        if patch.id == patch_id:
            return patch
    return None


def get_categories() -> list[PatchCategory]:
    """Get all categories with counts"""
    if not _categories:
        load_patches()

    # Recalculate counts from current patches
    category_counts: dict[str, int] = {}
    for patch in _patches:
        cat_id = patch.category.lower().replace(" ", "-")
        category_counts[cat_id] = category_counts.get(cat_id, 0) + 1

    return [
        PatchCategory(id=c.id, name=c.name, count=category_counts.get(c.id, 0))
        for c in _categories
    ]


# Load patches on module import
load_patches()
