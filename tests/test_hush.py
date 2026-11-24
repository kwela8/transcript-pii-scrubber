"""Tests for hush: python3 -m unittest discover -s tests (from the repository root)."""
from __future__ import annotations

import importlib.util
import io
import json
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

from hush import Hush, Person, config, core, presets, residual, transcripts  # noqa: E402
from hush.people import People, read_people, table_people  # noqa: E402
from hush.tables import scrub_csv  # noqa: E402
from hush import __main__ as cli  # noqa: E402

EDU = config.load(ROOT / "examples/education/hush.toml")
CALLS = ROOT / "examples/support-call/hush.toml"
DOCS = ROOT / "examples/llm-document/hush.toml"

CLASS = [Person("Aisha", "Khan", username="akhan23", id="K801200345017"),
         Person("Grace", "Okafor"), Person("William", "Baker", preferred="Will"),
         Person("Zoë", "Lark"), Person("Jayden", "Smith-Okoro"),
         Person("Alexander", "Reeve", preferred="Alex"), Person("Summer", "Holloway")]


def share(text, roster=CLASS, **kw):
    """The education example, as hush 0.1.0 ran school text."""
    return Hush("share", config=EDU, people=roster, **kw).scrub(text).text


def plain(text, preset="share", **kw):
    """hush with no config: the general defaults."""
    return Hush(preset, **kw).scrub(text).text


def kinds(text, **kw):
    out, _mapping = core.scrub(text, **kw)
    return {m.group("kind") for m in core.TOKEN.finditer(out)}


def cfg(**data):
    return config.from_dict(data)


# --- the education example: hush 0.1.0's school behaviour ---------------------------
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

    def test_read_people_csv(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("Name,Reg\nKhan, Aisha,9X\n")
            f.write('"Okafor, Grace",9X\n')
        try:
            people = read_people(f.name)
        finally:
            os.unlink(f.name)
        self.assertIn(Person("Grace", "Okafor"), people)

    def test_read_people_needs_a_name_column(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("Reg,Year\n9X,9\n")
        try:
            with self.assertRaises(ValueError):
                read_people(f.name)
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
        self.assertNotIn("Musa", plain("Musa joined yesterday."))

    def test_protected_words_stay(self):
        text = "Pythagoras' theorem and Pascal's triangle in Independent Learning on Monday."
        self.assertEqual(share(text, roster=()), text)

    def test_place_after_in(self):
        self.assertIn("Jordan", plain("The trip in Jordan was cancelled."))

    def test_unknown_surname_before_has(self):
        self.assertNotIn("Brathwaite", plain("Brathwaite has been late."))
        self.assertIn("Homework", share("Homework has been set.", roster=()))


class TheGuess(unittest.TestCase):
    def test_title_case_school_words_stay(self):
        text = ("Topic: Simultaneous Equations. Access Arrangements give Extra Time. "
                "Q: Will this mark do? The Summer Fair is at Hope Street Hall.")
        self.assertEqual(share(text, roster=()), text)

    def test_common_names_that_are_words_still_go(self):
        out = plain("Could you have a word with Hope? Paper copy for Grant, please.")
        self.assertNotIn("Hope", out)
        self.assertNotIn("Grant", out)

    def test_a_surname_beside_a_name(self):
        self.assertNotIn("Oyelaran", plain("I spoke to Tobi Oyelaran today."))


class LoginsAndTables(unittest.TestCase):
    def test_handles_stay_whole(self):
        out = plain("**@jordan.p** 10:41 AM\n@here the export is late")
        self.assertNotIn("jordan", out)
        self.assertIn("@here", out)

    def test_chat_speakers_shaped_like_logins(self):
        out = plain("[10:02] ms_bell: anyone know why\n[10:03] sam.k: yes")
        self.assertNotIn("ms_bell", out)
        self.assertNotIn("sam.k", out)

    def test_labelled_and_shaped_usernames(self):
        out = plain('user=holly.a then "username": "kai.r" and freddie.h')
        for value in ("holly", "kai.r", "freddie"):
            self.assertNotIn(value, out)

    def test_dotted_words_stay(self):
        text = "leaderboard.update and summer.term and max.value"
        self.assertEqual(share(text, roster=()), text)

    def test_a_pasted_table_is_its_own_list(self):
        text = "Forename\tSurname\tYear\nMiracle\tNwosu\t10\nSky\tDolan\t10\n\nMiracle is top."
        self.assertEqual(len(table_people(text)), 2)
        out = plain(text)
        for value in ("Miracle", "Nwosu", "Sky", "Dolan"):
            self.assertNotIn(value, out)

    def test_screenshot_misreads(self):
        known = [Person("Jakub", "Zielinski"), Person("Inês", "Carvalho")]
        out = plain("Zlelinski and Carva1ho", people=known)
        self.assertNotIn("Zlelinski", out)
        self.assertNotIn("Carva1ho", out)


class Presets(unittest.TestCase):
    TEXT = "Hi Mrs Pemberton, Aisha Khan (akhan23) rang 07700 900123. Aisha is fine."

    def test_ask_ai_restores_exactly(self):
        result = Hush("ask-ai", people=CLASS).scrub(self.TEXT)
        self.assertNotIn("Aisha", result.text)
        self.assertEqual(result.restore(result.text), self.TEXT)

    def test_share_labels_and_title(self):
        out = share(self.TEXT)
        self.assertIn("Mrs [person 1]", out)
        self.assertEqual(out.count("[student 1]"), 2)

    def test_known_people_are_labelled_by_role(self):
        out = plain(self.TEXT, people=CLASS)
        self.assertEqual(out.count("[person 2]"), 2)
        customers = [Person("Aisha", "Khan", role="customer")]
        self.assertEqual(plain(self.TEXT, people=customers).count("[customer 1]"), 2)

    def test_one_way_presets_refuse_restore(self):
        with self.assertRaises(ValueError):
            Hush("share").scrub("x").restore("x")

    def test_pseudonyms_follow_the_key(self):
        a = Hush("dataset", config=EDU, people=CLASS, key=b"k1").scrub("Aisha Khan").text
        b = Hush("dataset", config=EDU, people=CLASS, key=b"k1").scrub("aisha").text
        c = Hush("dataset", config=EDU, people=CLASS, key=b"k2").scrub("Aisha Khan").text
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertRegex(a, r"\AStudent-[0-9A-F]{6}\Z")
        self.assertRegex(plain("Aisha Khan", "dataset", people=CLASS, key=b"k1"),
                         r"\APerson-[0-9A-F]{6}\Z")

    def test_fakes_are_never_a_real_name_on_the_list(self):
        known = [Person(n, "Smith") for n in ("Olivia", "Amelia", "Isla", "Ava", "Mia")]
        out = Hush("demo", people=known, key=b"k").scrub(" ".join(p.first for p in known)).text
        for person in known:
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

    def test_a_full_name_and_its_first_name_share_a_label(self):
        out = plain("Gareth Lyle rang. Gareth said the parcel was late.")
        self.assertEqual(out, "[person 1] rang. [person 1] said the parcel was late.")


class Tables(unittest.TestCase):
    CSV = ("Forename,Surname,DOB,Postcode,Username,XP,Comment\n"
           "Aisha,Khan,03/04/2012,EX1 9ZZ,akhan23,1840,Aisha has improved.\n"
           "Musa,Bangura,22/01/2012,EX4 9ZZ,mbangura,0,Musa sits with Aisha.\n")

    def test_dataset_columns(self):
        out, report = scrub_csv(self.CSV, "dataset", config=EDU, key=b"k")
        rows = [line.split(",") for line in out.strip().split("\n")]
        aisha = rows[1][0]
        self.assertRegex(aisha, r"\AStudent-[0-9A-F]{6}\Z")
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

    def test_role_and_id_columns(self):
        text = "Name,Role,ID,Notes\nNadia Ferro,customer,AC-1182,Nadia rang twice.\n"
        out, report = scrub_csv(text, "share")
        self.assertEqual(out.splitlines()[1], "[customer 1],customer,[ID 1],[customer 1] rang twice.")
        self.assertEqual(report["columns"]["ID"], "id")


# --- packs ------------------------------------------------------------------------
class Packs(unittest.TestCase):
    def test_uk_pack_finds_uk_shapes(self):
        text = "NHS number 943 476 5919, send it to EX1 9ZZ, NI QQ 12 34 56 C"
        self.assertTrue({"NHSNUM", "POSTCODE", "NINO"} <= kinds(text))
        off = kinds(text, packs=("general",))
        self.assertFalse({"NHSNUM", "POSTCODE", "NINO"} & off)

    def test_general_pack_alone_still_finds_contact_details(self):
        found = kinds("mail ada@example.test, +33 1 23 45 67 89, card 4111 1111 1111 1111",
                      packs=("general",))
        self.assertTrue({"EMAIL", "PHONE", "CARD"} <= found)

    def test_south_africa_is_off_by_default(self):
        self.assertNotIn("south-africa", core.DEFAULT_PACKS)
        self.assertIn("ADDRESS", kinds("Ons woon in 12 Kerkstraat.", packs=("general", "south-africa")))
        self.assertNotIn("ADDRESS", kinds("Ons woon in 12 Kerkstraat."))

    def test_unknown_pack_is_an_error(self):
        with self.assertRaises(ValueError):
            core.packs_for(["nope"])
        with self.assertRaises(ValueError):
            cfg(packs={"nope": True})

    def test_second_check_reads_the_same_packs(self):
        self.assertFalse(residual.check("Post to EX1 9ZZ")["clean"])
        self.assertTrue(residual.check("Post to EX1 9ZZ", packs=("general",))["clean"])

    def test_school_ids_are_not_built_in(self):
        self.assertNotIn("UPN", kinds("UPN K801200345017"))
        self.assertIn("UPN", Hush("ask-ai", config=EDU).scrub("UPN K801200345017").tokens)


# --- the config file --------------------------------------------------------------
class Config(unittest.TestCase):
    def test_examples_load(self):
        for path in (CALLS, DOCS, ROOT / "examples/education/hush.toml"):
            loaded = config.load(path)
            self.assertTrue(loaded.name)

    def test_toml_and_json_agree(self):
        data = {"preset": "logs", "flag": ["DATE"], "packs": {"north-america": False},
                "words": {"keep": ["Kestrel"]},
                "detectors": [{"kind": "ORDER", "label": "order", "pattern": "ORD-\\d{6}"}],
                "redact": [{"kind": "CLIENT", "label": "client", "words": ["Halvorsen Freight"]}],
                "labels": {"PHONE": "telephone"}}
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.json").write_text(json.dumps(data), encoding="utf-8")
            Path(tmp, "a.toml").write_text(
                'preset = "logs"\nflag = ["DATE"]\n[packs]\nnorth-america = false\n'
                '[words]\nkeep = ["Kestrel"]\n[[detectors]]\nkind = "ORDER"\nlabel = "order"\n'
                "pattern = 'ORD-\\d{6}'\n[[redact]]\nkind = \"CLIENT\"\nlabel = \"client\"\n"
                'words = ["Halvorsen Freight"]\n[labels]\nPHONE = "telephone"\n',
                encoding="utf-8")
            a, b = config.load(Path(tmp, "a.json")), config.load(Path(tmp, "a.toml"))
        for field in ("preset", "flag", "packs", "keep_words", "labels"):
            self.assertEqual(getattr(a, field), getattr(b, field), field)
        self.assertEqual(a.packs, ("general", "uk"))
        out = Hush(config=b).scrub("Kestrel order ORD-123456 for Halvorsen Freight, "
                                   "ring 07700 900123 on 3 March 2026").text
        self.assertEqual(out, "Kestrel order [order 1] for [client 1], ring [telephone 1] on "
                              "3 March 2026")

    def test_files_are_read_from_the_config_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "keep.txt").write_text("# products\nMarlow\n", encoding="utf-8")
            Path(tmp, "people.csv").write_text("First,Last,Role\nNadia,Ferro,customer\n",
                                               encoding="utf-8")
            Path(tmp, "hush.toml").write_text(
                '[words]\nkeep_files = ["keep.txt"]\n[people]\nknown = ["people.csv"]\n',
                encoding="utf-8")
            loaded = config.load(Path(tmp, "hush.toml"))
        self.assertIn("Marlow", loaded.keep_words)
        self.assertEqual(plain("Marlow rang Nadia.", config=loaded), "Marlow rang [customer 1].")

    def test_mistakes_are_named(self):
        for bad in ({"colour": "red"}, {"preset": "loud"}, {"words": {"kep": []}},
                    {"detectors": [{"kind": "x", "pattern": "a"}]},
                    {"detectors": [{"kind": "ORDER", "pattern": "("}]},
                    {"transcript": {"speakers": "drop"}}, {"flag": "DATE"} and {"flag": [1]}):
            with self.assertRaises(ValueError, msg=bad):
                cfg(**bad)

    def test_flagged_kinds_stay_and_are_listed(self):
        result = Hush(config=cfg(flag=["DATE"])).scrub("Ordered on 3 March 2026 by Nadia Ferro.")
        self.assertEqual(result.text, "Ordered on 3 March 2026 by [person 1].")
        self.assertEqual([f["kind"] for f in result.flags], ["DATE"])
        flag = result.flags[0]
        self.assertEqual(result.text[flag["start"]:flag["end"]], "3 March 2026")
        self.assertNotIn("DATE", result.removed)


# --- names to keep ------------------------------------------------------------------
class KeepNames(unittest.TestCase):
    def test_kept_people_stay_in_every_form(self):
        keep = [Person("Priya", "Shah")]
        out = plain("Priya Shah spoke to Tom Barker. Priya said Mr Barker would ring Ms Shah.",
                    keep=keep)
        self.assertEqual(out, "Priya Shah spoke to [person 1]. Priya said Mr [person 1] "
                              "would ring Ms Shah.")

    def test_a_kept_first_name_with_another_surname_goes(self):
        out = plain("Priya Shah and Priya Okonjo both rang.", keep=[Person("Priya", "Shah")])
        self.assertIn("Priya Shah", out)
        self.assertNotIn("Okonjo", out)

    def test_keep_from_a_file_by_cli(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Priya Shah\n")
        try:
            code, out, _err = CommandLine.run_cli(None, "scrub", "--keep", f.name,
                                                  stdin="Priya Shah rang Tom Barker.")
        finally:
            os.unlink(f.name)
        self.assertEqual((code, out), (0, "Priya Shah rang [person 1]."))

    def test_keep_wins_over_the_known_list(self):
        out = plain("Nadia Ferro rang.", people=[Person("Nadia", "Ferro")],
                    keep=[Person("Nadia", "Ferro")])
        self.assertEqual(out, "Nadia Ferro rang.")


# --- transcripts -------------------------------------------------------------------
CALL = """[00:00:01] Agent: Thanks for calling, you're through to Priya Shah.
00:00:04 Customer: Hi, it's Daniel Okafor. My son Tom Barker placed the order.
Speaker 2: and my wife Helen said it was charged twice.
SPEAKER_01: ok
DANIEL (10:02): my postcode is EX1 9ZZ.
Subject: refund
Priya Shah [00:01:02]: I've raised it with my manager, Carl Jensen.
<v Ruth Adair>Can you hear me?</v>
"""


class SpeakerLabels(unittest.TestCase):
    def test_the_shapes(self):
        found = [(s.name, s.generic) for s in transcripts.speakers(CALL)]
        self.assertEqual(found, [("Agent", True), ("Customer", True), ("Speaker 2", True),
                                 ("SPEAKER_01", True), ("DANIEL", False),
                                 ("Priya Shah", False), ("Ruth Adair", False)])

    def test_headings_and_fields_are_not_speakers(self):
        names = [s.name for s in transcripts.speakers("Subject: x\nNote: y\nAttendees: z\n"
                                                      "Error: failed\nDear Sam,\n")]
        self.assertEqual(names, [])

    def test_a_one_word_speaker_takes_the_fuller_name(self):
        self.assertEqual(transcripts.named_speakers(CALL),
                         ["Daniel Okafor", "Priya Shah", "Ruth Adair"])

    def test_keep_mode_keeps_the_speakers(self):
        out = Hush(config=cfg(transcript={"speakers": "keep"})).scrub(CALL).text
        for name in ("Priya Shah", "Daniel Okafor", "DANIEL (10:02)", "Ruth Adair"):
            self.assertIn(name, out)
        for name in ("Tom Barker", "Helen", "Carl Jensen"):
            self.assertNotIn(name, out)

    def test_relabel_mode_gives_each_speaker_one_placeholder(self):
        h = Hush(config=cfg(transcript={"speakers": "relabel",
                                        "roles": {"Priya Shah": "agent"}}))
        out = h.scrub(CALL).text
        self.assertIn("[agent 1] [00:01:02]:", out)
        self.assertIn("you're through to [agent 1].", out)
        self.assertIn("it's [speaker 1].", out)
        self.assertIn("[speaker 1] (10:02):", out)
        self.assertIn("Agent:", out)

    def test_text_mode_treats_labels_as_text(self):
        out = plain(CALL)
        self.assertNotIn("Priya", out)
        self.assertIn("Agent:", out)


class RoleCues(unittest.TestCase):
    def test_a_cue_word_names_the_role_and_flags_it(self):
        h = Hush(config=cfg(cues={"family": ["son", "wife"], "staff": ["manager"]}))
        result = h.scrub(CALL)
        self.assertIn("My son [family 1] placed", result.text)
        self.assertIn("my wife [family 2] said", result.text)
        self.assertIn("my manager, [staff 1].", result.text)
        self.assertEqual(sorted(f["kind"] for f in result.flags),
                         ["PERSON_FAMILY", "PERSON_FAMILY", "PERSON_STAFF"])
        self.assertTrue(all(f["why"].startswith("role cue") for f in result.flags))

    def test_a_cue_in_the_next_sentence_does_not_count(self):
        h = Hush(config=cfg(cues={"family": ["son"]}))
        self.assertEqual(h.scrub("I rang Tom Barker. My son was out.").text,
                         "I rang [person 1]. My son was out.")


class SpeechToText(unittest.TestCase):
    ASR = ("agent. thank you for calling. customer. hi yeah my name is daniel okafor and my "
           "number is oh seven seven double oh nine hundred one two three and my email is "
           "dan dot okafor at example dot com")

    def test_lower_case_names_numbers_and_emails(self):
        out = plain(self.ASR)
        self.assertEqual(out, "agent. thank you for calling. customer. hi yeah my name is "
                              "[person 1] and my number is [phone 1] and my email is [email 1]")

    def test_a_lower_case_word_after_a_name_stays(self):
        self.assertEqual(plain("yeah daniel said it was fine"),
                         "yeah [person 1] said it was fine")


# --- command line, bench, core -------------------------------------------------------
class CommandLine(unittest.TestCase):
    def run_cli(self, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                mock.patch.object(sys, "stdin", io.StringIO(stdin)):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_scrub_from_stdin_with_a_config(self):
        code, out, err = self.run_cli(
            "scrub", "--config", str(ROOT / "examples/education/hush.toml"),
            "--roster", str(ROOT / "examples/education/class-9X.csv"), stdin="Aisha and Bartek")
        self.assertEqual(code, 0)
        self.assertEqual(out, "[student 1] and [student 2]")
        self.assertIn("PERSON_STUDENT", err)
        self.assertNotIn("Aisha", err)

    def test_people_without_a_config(self):
        code, out, _err = self.run_cli(
            "scrub", "--people", str(ROOT / "examples/education/class-9X.csv"),
            stdin="Aisha and Bartek")
        self.assertEqual((code, out), (0, "[person 1] and [person 2]"))

    def test_flags_are_reported_without_values(self):
        code, out, err = self.run_cli("scrub", "--config", str(CALLS), "--json",
                                      stdin="Gareth Lyle: my son Callum rang on 2 May 2026.")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual([f["kind"] for f in data["flags"]], ["PERSON_FAMILY", "DATE"])
        self.assertNotIn("Callum", out)

    def test_bad_config_exits_2(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write('preset = "loud"\n')
        try:
            code, _out, err = self.run_cli("scrub", "--config", f.name, stdin="x")
        finally:
            os.unlink(f.name)
        self.assertEqual(code, 2)
        self.assertIn("preset", err)

    def test_key_env_must_be_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                self.run_cli("scrub", "--key-env", "HUSH_TEST_KEY")

    def test_module_runs(self):
        for verb, word in (("presets", "ask-ai"), ("packs", "south-africa")):
            done = subprocess.run([sys.executable, "-m", "hush", verb], cwd=ROOT,
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0)
            self.assertIn(word, done.stdout)


def _bench():
    spec = importlib.util.spec_from_file_location("hush_bench", ROOT / "bench/bench.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TheBench(unittest.TestCase):
    def test_education_share_preset_holds_its_figures(self):
        bench = _bench()
        data = json.loads((ROOT / "bench/education/cases_1.json").read_text(encoding="utf-8"))
        options = dict((n, (o, k)) for n, o, k in bench.columns(EDU))["share preset"]
        result = bench.run(data["cases"], data["negatives"], Hush(config=EDU, **options[0]),
                           options[1], tuple(data["unscored"]))
        student = result["types"]["STUDENT"]
        self.assertEqual((student["caught"], student["occ"]), (766, 784))   # 97.7%
        self.assertEqual(result["restore_exact"], result["restore_total"])
        self.assertEqual(result["fp_negatives"], 7)

    def test_general_set_restores_and_keeps(self):
        bench = _bench()
        data = json.loads((ROOT / "bench/general/cases.json").read_text(encoding="utf-8"))
        result = bench.run(data["cases"], data["negatives"], Hush("share"), True,
                           tuple(data.get("unscored", ())))
        # Two cases write one name in two cases of letter; restore gives
        # back the first spelling, so they differ only in case.
        self.assertGreaterEqual(result["restore_exact"], result["restore_total"] - 2)
        self.assertEqual(result["kept_intact"], result["kept_total"])
        person = result["types"]["PERSON"]
        self.assertGreaterEqual(person["caught"] / person["occ"], 0.85)


class Core(unittest.TestCase):
    def test_core_alone_still_restores(self):
        text = "Ada Quill, NHS 943 476 5919, ada@example.test"
        out, mapping = core.scrub(text)
        self.assertEqual(core.restore(out, mapping), text)

    def test_detector_respects_existing_tokens(self):
        people = People(CLASS)
        out, mapping = core.scrub("aisha.khan@example.test and Aisha", people=people.detector)
        self.assertEqual(out.count("<P"), 2)
        self.assertEqual(core.restore(out, mapping), "aisha.khan@example.test and Aisha")

    def test_the_older_detector_name_still_works(self):
        out, _mapping = core.scrub("Aisha rang", students=People(CLASS).detector)
        self.assertNotIn("Aisha", out)

    def test_fake_names_keep_the_sex_from_the_first_call(self):
        done = subprocess.run([sys.executable, "-c", "from hush.styles import sex_of; "
                               "print(sex_of('Gareth'), sex_of('Grace'))"], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.stdout.split(), ["b", "g"])

    def test_role_kinds(self):
        self.assertEqual(core.role_kind("third party"), "PERSON_THIRD_PARTY")
        self.assertEqual(core.role_kind(""), "PERSON")
        self.assertTrue(core.is_name_kind("PERSON_CUSTOMER"))
        self.assertFalse(core.is_name_kind("EMAIL"))


# --- found by the public benchmark ---------------------------------------------------
def _left(name, out):
    """The words of ``name`` still in ``out``, and any word of ``out`` that holds a piece of
    one (a cut name leaves "[person 1]łąkski")."""
    import re
    words = re.findall(r"\w+", name)
    return [w for w in re.findall(r"\w+", out)
            if any(w in n or n in w for n in words) and w not in ("person", "1", "2")]


class LettersWithMarks(unittest.TestCase):
    NAMES = ("Wołąkski", "Kaşıkçı", "Dvořák", "Bērziņš", "Kūrinas", "Ørsted", "Ćosić",
             "Şahin", "İnce", "Ğürbüz", "Ōtsuka", "Țepeș", "Ęgle", "Ősz", "Đặng")

    def test_a_titled_name_goes_whole_and_its_title_stays(self):
        for name in self.NAMES:
            self.assertEqual(plain("Mr %s called today." % name), "Mr [person 1] called today.",
                             name)

    def test_an_initial_and_a_surname_go_together(self):
        self.assertEqual(plain("Mr T. Wołąkski signed it."), "Mr [person 1] signed it.")
        self.assertEqual(plain("Dr Ł. Wołąkska signed it."), "Dr [person 1] signed it.")

    def test_names_without_a_title_go_whole(self):
        for text, name in (("I spoke to Ēriks Bērziņš yesterday.", "Ēriks Bērziņš"),
                           ("Report by Kaşıkçı, signed.", "Kaşıkçı"),
                           ("The file went to Ørjan Ørsted on Friday.", "Ørjan Ørsted"),
                           ("We met Ćiro Ćosić and Petr Dvořák.", "Ćiro Ćosić Petr Dvořák"),
                           ("Copy to Anna Kowalska-Łącka please.", "Anna Kowalska-Łącka")):
            self.assertEqual(_left(name, plain(text)), [], text)
            self.assertEqual(_left(name, core.scrub(text)[0]), [], text)


class LongCodes(unittest.TestCase):
    def test_a_ten_digit_run_inside_a_code_goes_with_the_code(self):
        for text in ("My biometric identifier is BIO-5724169380", "ref 078-3527149560 ok",
                     "device SN-0042-5724169380-X"):
            for out in (plain(text), core.TOKEN.sub("<T>", core.scrub(text)[0])):
                self.assertNotRegex(out, r"BIO|\d{3}|SN-", text)

    def test_school_numbers_are_only_in_the_education_example(self):
        rules = core._rules(tuple(core.PACKS))
        self.assertFalse({"UPN", "ULN"} & {rule.kind for rule in rules})
        self.assertFalse([rule for rule in rules
                          if rule.pattern.pattern.replace("(?<![A-Za-z0-9.,])", "") == r"\d{10}"])


if __name__ == "__main__":
    unittest.main()
