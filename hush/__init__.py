"""hush: find personal data in text, pupils' names first, and replace it.

    from hush import Hush, read_roster
    result = Hush("share", roster=read_roster("class.csv")).scrub(text)

See README.md for the five presets and what was measured. Standard library only.
"""
from hush.presets import PRESETS, Hush, Preset, Result
from hush.students import Person, Pupils, read_roster

__all__ = ["Hush", "PRESETS", "Preset", "Result", "Person", "Pupils", "read_roster"]
__version__ = "0.1.0"
