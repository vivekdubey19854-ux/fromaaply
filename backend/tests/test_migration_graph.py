from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_has_one_head_after_phase5a_merge():
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1
    assert heads[0] == "0016_unified_provider_control_plane"
