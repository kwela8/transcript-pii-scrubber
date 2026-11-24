"""hush: check a transcript or any text for chosen kinds of personal data, and replace it
before the text goes to an AI model, a chat, a dataset or a log.

    from hush import Hush
    result = Hush("share", config="examples/support-call/hush.toml").scrub(text)

See README.md for the presets, the packs, the config file and what was measured.
Standard library only.
"""
from hush.config import Config, load as load_config
from hush.people import Detector, People, Person, read_names, read_people, read_roster
from hush.presets import PRESETS, Hush, Preset, Result

__all__ = ["Hush", "PRESETS", "Preset", "Result", "Config", "load_config", "Detector",
           "People", "Person", "read_people", "read_roster", "read_names"]
__version__ = "0.2.0"
