"""Tests for hush: python3 -m unittest discover -s tests (from the repository root)."""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hush import Hush, Person, core, presets  # noqa: E402
from hush.students import Pupils, read_roster, table_people  # noqa: E402
from hush.tables import scrub_csv  # noqa: E402
from hush import __main__ as cli  # noqa: E402

CLASS = [Person("Aisha", "Khan", username="akhan23", upn="K801200345017"),
         Person("Grace", "Okafor"), Person("William", "Baker", preferred="Will"),
         Person("Zoë", "Lark"), Person("Jayden", "Smith-Okoro"),
         Person("Alexander", "Reeve", preferred="Alex"), Person("Summer", "Holloway")]


def share(text, roster=CLASS, **kw):
    return Hush("share", roster=roster, **kw).scrub(text).text


class TheClassList(unittest.TestCase):
    def test_full_and_first_names_in_any_case(self):
        out = share("Aisha Khan and aisha and AISHA KHAN and Khan, Aisha")
        self.assertNotIn("isha", out.lower())
        self.assertNotIn("khan", out.lower())

    def test_possessive_keeps_the_s(self):
        self.assertEqual(share("Aisha's login"), "[student 1]'s login")

    def test_accents_fold(self):
        self.assertNotIn("Zoe", share("Zoe Lark finished."))

    def test_hyphenated_surname_whole_and_parts(self):
        out = share("Jayden Smith-Okoro, then Smith-Okoro again.")
        self.assertNotIn("Smith", out)
        self.assertNotIn("Okoro", out)

    def test_preferred_name_is_the_same_pupil(self):
        out = share("Alexander Reeve, known as Alex. Alex is fine.")
        self.assertEqual(out.count("[student 1]"), 3)

    def test_identifiers_on_the_roster(self):
        out = share("login akhan23, UPN K801200345017")
        self.assertNotIn("akhan23", out)
        self.assertNotIn("K801200345017", out)

    def test_read_roster_csv(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("Name,Reg\nKhan, Aisha,9X\n")
            f.write('"Okafor, Grace",9X\n')
        try:
            people = read_roster(f.name)
        finally:
            os.unlink(f.name)
        self.assertIn(Person("Grace", "Okafor"), people)

    def test_read_roster_needs_a_name_column(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("Reg,Year\n9X,9\n")
        try:
            with self.assertRaises(ValueError):
                read_roster(f.name)
        finally:
            os.unlink(f.name)


class NamesThatAreWords(unittest.TestCase):
    def test_will_the_pupil_and_will_the_verb(self):
        out = share("Will is off sick. Will you check it? Grace period ends Friday.")
        self.assertTrue(out.startswith("[student 1] is off sick. Will you check it? Grace period"))

    def test_phrases_stay(self):
        out = share("The Summer Term and the Mark Scheme. Summer Term starts.")
        self.assertEqual(out, "The Summer Term and the Mark Scheme. Summer Term starts.")

    def test_lower_case_word_name_only_before_a_verb(self):
        self.assertIn("grace", share("by the grace of the timetable"))
        self.assertNotIn("grace", share("grace hasn't logged in"))

    def test_verb_shaped_word_after_a_roster_name_word(self):
        self.assertNotIn("Summer", share("Summer finds fractions hard."))


class TheFirstNameList(unittest.TestCase):
    def test_sentence_start_name_off_the_roster(self):
        out = share("Musa joined yesterday.", roster=())
        self.assertNotIn("Musa", out)

    def test_protected_words_stay(self):
        text = "Pythagoras' theorem and Pascal's triangle in Independent Learning on Monday."
        self.assertEqual(share(text, roster=()), text)

    def test_place_after_in(self):
        self.assertIn("Jordan", share("The trip in Jordan was cancelled.", roster=()))

    def test_unknown_surname_before_has(self):
        self.assertNotIn("Brathwaite", share("Brathwaite has been late.", roster=()))
        self.assertIn("Homework", share("Homework has been set.", roster=()))


class TheGuess(unittest.TestCase):
    def test_title_case_school_words_stay(self):
        text = ("Topic: Simultaneous Equations. Access Arrangements give Extra Time. "
                "Q: Will this mark do? The Summer Fair is at Hope Street Hall.")
        self.assertEqual(share(text, roster=()), text)

    def test_common_names_that_are_words_still_go(self):
        out = share("Could you have a word with Hope? Paper copy for Grant, please.",
                    roster=())
        self.assertNotIn("Hope", out)
        self.assertNotIn("Grant", out)

    def test_a_surname_beside_a_name(self):
        self.assertNotIn("Oyelaran", share("I spoke to Tobi Oyelaran today.", roster=()))


class LoginsAndTables(unittest.TestCase):
    def test_handles_stay_whole(self):
        out = share("**@jordan.p** 10:41 AM\n@here the export is late", roster=())
        self.assertNotIn("jordan", out)
        self.assertIn("@here", out)

    def test_chat_speakers_shaped_like_logins(self):
        out = share("[10:02] ms_bell: anyone know why\n[10:03] sam.k: yes", roster=())
        self.assertNotIn("ms_bell", out)
        self.assertNotIn("sam.k", out)

    def test_labelled_and_shaped_usernames(self):
        out = share('user=holly.a then "username": "kai.r" and freddie.h', roster=())
        for value in ("holly", "kai.r", "freddie"):
            self.assertNotIn(value, out)

    def test_dotted_words_stay(self):
        text = "leaderboard.update and summer.term and max.value"
        self.assertEqual(share(text, roster=()), text)

    def test_a_pasted_table_is_its_own_roster(self):
        text = "Forename\tSurname\tYear\nMiracle\tNwosu\t10\nSky\tDolan\t10\n\nMiracle is top."
        self.assertEqual(len(table_people(text)), 2)
        out = share(text, roster=())
        for value in ("Miracle", "Nwosu", "Sky", "Dolan"):
            self.assertNotIn(value, out)

    def test_screenshot_misreads(self):
        roster = [Person("Jakub", "Zielinski"), Person("Inês", "Carvalho")]
        out = share("Zlelinski and Carva1ho", roster=roster)
        self.assertNotIn("Zlelinski", out)
        self.assertNotIn("Carva1ho", out)


class Presets(unittest.TestCase):
    TEXT = "Hi Mrs Pemberton, Aisha Khan (akhan23) rang 07700 900123. Aisha is fine."

    def test_ask_ai_restores_exactly(self):
        result = Hush("ask-ai", roster=CLASS).scrub(self.TEXT)
        self.assertNotIn("Aisha", result.text)
        self.assertEqual(result.restore(result.text), self.TEXT)

    def test_share_labels_and_title(self):
        out = share(self.TEXT)
        self.assertIn("Mrs [person 1]", out)
        self.assertEqual(out.count("[student 1]"), 2)

    def test_one_way_presets_refuse_restore(self):
        with self.assertRaises(ValueError):
            Hush("share").scrub("x").restore("x")

    def test_pseudonyms_follow_the_key(self):
        a = Hush("dataset", roster=CLASS, key=b"k1").scrub("Aisha Khan").text
        b = Hush("dataset", roster=CLASS, key=b"k1").scrub("aisha").text
        c = Hush("dataset", roster=CLASS, key=b"k2").scrub("Aisha Khan").text
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertRegex(a, r"\APupil-[0-9A-F]{6}\Z")

    def test_fakes_are_never_a_real_name_on_the_roster(self):
        roster = [Person(n, "Smith") for n in ("Olivia", "Amelia", "Isla", "Ava", "Mia")]
        h = Hush("demo", roster=roster, key=b"k")
        out = h.scrub(" ".join(p.first for p in roster)).text
        for person in roster:
            self.assertNotIn(person.first, out.split())

    def test_logs_take_titled_names_without_the_guess(self):
        result = Hush("logs").scrub("ERROR UserService: Ms Lindqvist reset failed")
        self.assertFalse(result.refused)
        self.assertIn("UserService", result.text)
        self.assertNotIn("Lindqvist", result.text)

    def test_refusal_sends_nothing(self):
        with mock.patch.object(presets.residual, "check",
                               return_value={"clean": False, "found": {"PHONE": 1}}):
            result = Hush("share").scrub("anything")
        self.assertTrue(result.refused)
        self.assertEqual(result.text, "")

    def test_unknown_preset_and_option(self):
        with self.assertRaises(ValueError):
            Hush("nope")
        with self.assertRaises(ValueError):
            Hush("share", colour="red")


class Tables(unittest.TestCase):
    CSV = ("Forename,Surname,DOB,Postcode,Username,XP,Comment\n"
           "Aisha,Khan,03/04/2012,EX1 9ZZ,akhan23,1840,Aisha has improved.\n"
           "Musa,Bangura,22/01/2012,EX4 9ZZ,mbangura,0,Musa sits with Aisha.\n")

    def test_dataset_columns(self):
        out, report = scrub_csv(self.CSV, "dataset", key=b"k")
        rows = [line.split(",") for line in out.strip().split("\n")]
        aisha = rows[1][0]
        self.assertRegex(aisha, r"\APupil-[0-9A-F]{6}\Z")
        self.assertEqual(rows[1][1], "")
        self.assertEqual(rows[1][2:4], ["2012", "EX1"])
        self.assertRegex(rows[1][4], r"\AUSERNAME-[0-9A-F]{6}\Z")
        self.assertEqual(rows[1][5], "1840")
        self.assertIn(aisha, rows[1][-1])
        self.assertIn(aisha, rows[2][-1])
        self.assertEqual(report["people"], 2)

    def test_no_name_survives_any_style(self):
        for preset in ("share", "dataset", "demo", "logs"):
            out, _ = scrub_csv(self.CSV, preset)
            for value in ("Aisha", "Khan", "Musa", "Bangura", "akhan23", "03/04/2012"):
                self.assertNotIn(value, out, (preset, value))


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                mock.patch.object(sys, "stdin", io.StringIO(stdin)):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_scrub_from_stdin(self):
        code, out, err = self.run_cli("scrub", "--roster", str(ROOT / "examples/class-9X.csv"),
                                      stdin="Aisha and Bartek")
        self.assertEqual(code, 0)
        self.assertEqual(out, "[student 1] and [student 2]")
        self.assertIn("STUDENT", err)
        self.assertNotIn("Aisha", err)

    def test_key_env_must_be_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                self.run_cli("scrub", "--key-env", "HUSH_TEST_KEY")

    def test_module_runs(self):
        done = subprocess.run([sys.executable, "-m", "hush", "presets"], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0)
        self.assertIn("ask-ai", done.stdout)


class TheBench(unittest.TestCase):
    def test_share_preset_holds_its_figures(self):
        sys.path.insert(0, str(ROOT / "bench"))
        import json
        import student_bench
        data = json.loads((ROOT / "bench/student_cases.json").read_text(encoding="utf-8"))
        cfg = dict(student_bench.CONFIGS)["share preset"]
        result = student_bench.run(data["cases"], data["negatives"], cfg)
        student = result["types"]["STUDENT"]
        self.assertGreaterEqual(student["caught"] / student["occ"], 0.97)
        self.assertEqual(result["restore_exact"], result["restore_total"])
        self.assertLessEqual(result["fp_negatives"], 7)


class Core(unittest.TestCase):
    def test_core_alone_still_restores(self):
        text = "Ada Quill, NHS 943 476 5919, ada@example.test"
        out, mapping = core.scrub(text)
        self.assertEqual(core.restore(out, mapping), text)

    def test_detector_respects_existing_tokens(self):
        pupils = Pupils(CLASS)
        out, mapping = core.scrub("aisha.khan@example.test and Aisha", students=pupils.detector)
        self.assertEqual(out.count("<P"), 2)
        self.assertEqual(core.restore(out, mapping), "aisha.khan@example.test and Aisha")


if __name__ == "__main__":
    unittest.main()
