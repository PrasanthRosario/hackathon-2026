from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
SCENES_DIR = REPOSITORY_ROOT / "scenes"
DEFAULT_SET_PATH = SCENES_DIR / "set.usda"
DEFAULT_ROOM_SET_PATH = SCENES_DIR / "room_set.usda"
DEFAULT_SCENE_DATA_PATH = SCENES_DIR / "scene_data.json"
