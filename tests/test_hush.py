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


class Phones(unittest.TestCase):
    def assertOnePhone(self, text, number):
        out = plain(text)
        self.assertEqual(out, text.replace(number, "[phone 1]"), text)
        result = Hush("ask-ai").scrub(text)
        self.assertEqual(result.restore(result.text), text)

    def test_extensions_go_with_the_number(self):
        for number in ("+1 202 555 0137 ext 11037", "(212) 555-0134 x12", "+1 212 555 0134 x 7",
                       "020 7946 0018 extension 204", "07700 900123 ext. 5",
                       "+44 20 7946 0018, ext 31", "212-555-0134 (ext. 220)"):
            self.assertOnePhone("Call %s today." % number, number)
        self.assertOnePhone("Phone number: +1 202 555 0137 ext 11037\n",
                            "+1 202 555 0137 ext 11037")

    def test_north_american_shapes(self):
        for number in ("(555) 015-7148", "(555)123-4567", "555-015-7148", "555.123.4567",
                       "+1 (555) 123-4567", "1-800-555-0199", "+1-212-555-0134", "212 555 0134"):
            self.assertOnePhone("customer rang from %s, ticket open." % number, number)

    def test_international_shapes(self):
        for number in ("+44 20 7946 0018", "+33.1.23.45.67.89", "+49-30-1234567",
                       "+966 55 123 4567", "+61 (0)2 9374 4000", "0049 30 1234567",
                       "(96) 3231-1432", "(81) 99138-7542"):
            self.assertOnePhone("Reach me on %s now." % number, number)

    def test_spoken_digits_with_fillers(self):
        text = "yeah my number is oh seven seven, um, double oh nine hundred, er, one two three"
        out = plain(text)
        self.assertEqual(out, "yeah my number is [phone 1]")
        text = "it's four one one one, uh, one two three four five six thanks"
        self.assertEqual(plain(text), "it's [number 1] thanks")
        result = Hush("ask-ai").scrub(text)
        self.assertEqual(result.restore(result.text), text)

    def test_not_phones(self):
        for text in ("Mix 2 x 3 boxes.", "Chapter 5 extension work is due.", "Pages 555-560.",
                     "In 2019-2020 we grew.", "The ext is fine.", "Order 12 x 400 g."):
            self.assertEqual(plain(text), text)


class Addresses(unittest.TestCase):
    def assertAddress(self, text, address, label="address"):
        self.assertEqual(plain(text), text.replace(address, "[%s 1]" % label), text)

    def test_street_unit_city_region_and_postal_code(self):
        for address in ("6090 Willowquill Ave., Apt 11, Silverholt",
                        "517 N Shelton Ave",
                        "139 Justin Dr, Claremont, CA 91711, USA",
                        "57 Arbor Trace Dr Unit E, Midlothian, VA 23112",
                        "350 Albert Street Suite 200",
                        "402 Dogwood Drive NW, TN",
                        "12 Hollin Road, Leeds LS6 2AB",
                        "Flat 3, 12 Hollin Road, Leeds",
                        "88 Rue Brisemoor Boulevard, Apartment 4B",
                        "108 39th Ave N, Murfreesboro, TN 37130",
                        "1 The Avenue, Ashcombe",
                        "15 St Mary's Road"):
            self.assertAddress("They live at %s now." % address, address)

    def test_post_office_boxes(self):
        for address in ("PO Box 4471", "P.O. Box 12, Springfield, IL 62701", "Post Office Box 7"):
            self.assertAddress("Write to %s please." % address, address)

    def test_a_city_region_and_zip_alone(self):
        self.assertAddress("Based in Murfreesboro, TN 37130 since May.", "Murfreesboro, TN 37130")
        self.assertAddress("From Austin, Texas, 78201 to here.", "Austin, Texas, 78201")

    def test_postal_codes_after_a_label(self):
        for text, code in (("Postcode: 17408", "17408"), ("**Postcode:** 60611", "60611"),
                           ("with a postal code of 13850, we", "13850"), ("ZIP: 07055", "07055"),
                           ("zip code 90210-1234.", "90210-1234"), ("Code postal A1B 2C3", "A1B 2C3")):
            self.assertEqual(plain(text), text.replace(code, "[postcode 1]"), text)

    def test_a_number_and_a_word_that_is_no_street_word_stay(self):
        for text in ("It takes 5 minutes down the road.", "We sold 3 Big Boxes.",
                     "Chapter 12 Main Points", "There are 4 Lanes here.",
                     "Step 2 Fill In The Way you like.", "Top 10 Places To Visit",
                     "We need 3 Dr appointments.", "In 1995 the court ruled."):
            self.assertEqual(plain(text), text)

    def test_an_address_street_named_like_a_person_goes_whole(self):
        self.assertAddress("Deliver to 22 Jordan Avenue, Hollow Bay.", "22 Jordan Avenue, Hollow Bay")


class Dates(unittest.TestCase):
    def assertDate(self, text, date, preset="share", **kw):
        self.assertEqual(plain(text, preset, **kw), text.replace(date, "[date 1]"), text)

    def test_a_date_with_its_time(self):
        for date in ("2025-01-08T14:31:17", "2023-10-05T14:48:00Z", "08/15/2023 19:45",
                     "2024-03-14 09:30:00", "14 March 2024 at 10:30",
                     "March 3, 2024, 2:30 PM", "2024-03-14T09:30:00+01:00"):
            self.assertDate("It was logged on %s by the desk." % date, date)

    def test_a_weekday_before_the_date(self):
        for date in ("Fri, 15 Dec 2023", "Monday 3 March 2024", "Tuesday, March 3rd"):
            self.assertDate("Seen on %s at the clinic." % date, date)

    def test_a_date_with_no_year(self):
        for date in ("March 3rd", "3rd of March", "December 31st", "15 March",
                     "fourteenth of March", "Dec 5", "September 15th"):
            self.assertDate("Due on %s, please." % date, date)

    def test_a_month_and_year(self):
        for date in ("October 2023", "Oct 2023", "March of 2024"):
            self.assertDate("Started in %s and stayed." % date, date)

    def test_words_that_only_look_like_dates_stay(self):
        for text in ("We march 3 miles a day.", "You may 2 times.", "May I have 3?",
                     "The Mars 2 rover.", "He read 3 of May's poems.", "In 2019 we grew.",
                     "Mix 10 to 12 June bugs.", "It costs 15 marks."):
            self.assertEqual(plain(text), text)

    def test_bare_years_are_left_by_default(self):
        for text in ("She was born in 1985.", "In 2019 we grew.", "Class of 2010."):
            self.assertEqual(plain(text), text)

    def test_bare_years_near_a_date_word_when_asked(self):
        years = cfg(dates={"years": "near"})
        for text, year in (("She was born in 1985.", "1985"), ("In 2019 we grew.", "2019"),
                           ("Class of 2010 met.", "2010"), ("Since 1999, nothing.", "1999")):
            self.assertEqual(plain(text, config=years), text.replace(year, "[year 1]"), text)
        for text in ("We sold 2019 units.", "Room 1985 is shut.", "It cost $2000 in all.",
                     "Python 3.2019 is odd."):
            self.assertEqual(plain(text, config=years), text)

    def test_every_bare_year_when_asked(self):
        every = cfg(dates={"years": "all"})
        self.assertEqual(plain("Team 2019 won.", config=every), "Team [year 1] won.")
        self.assertEqual(plain("It cost £2000.", config=every), "It cost £2000.")
        # A run of digit groups is a number, never two years.
        self.assertEqual(plain("Call 2019 2020 3333 now.", config=every), "Call [number 1] now.")

    def test_a_year_can_be_flagged_instead(self):
        flagged = cfg(dates={"years": "near"}, flag=["YEAR"])
        result = Hush("share", config=flagged).scrub("She was born in 1985.")
        self.assertEqual(result.text, "She was born in 1985.")
        self.assertEqual([f["kind"] for f in result.flags], ["YEAR"])

    def test_the_years_setting_is_checked(self):
        with self.assertRaises(ValueError):
            cfg(dates={"years": "some"})
        with self.assertRaises(ValueError):
            cfg(dates={"months": "all"})


class Usernames(unittest.TestCase):
    def assertUser(self, text, user):
        out = plain(text)
        self.assertNotIn(user, out, text)
        self.assertEqual(out, text.replace(user, "[username 1]"), text)

    def test_after_a_label(self):
        for text, user in (("**User Name:** Layla2025 | next", "Layla2025"),
                           ("- **User Name**: r.muniz", "r.muniz"),
                           ("The affected user name was mickeyberman.", "mickeyberman"),
                           ("The user name associated with this request was lovro_babic.",
                            "lovro_babic"),
                           ("Her username on the platform is aixa.echols.", "aixa.echols"),
                           ("The user Santiago2023 tried to log in.", "Santiago2023"),
                           ("It was run by user name m.demir.", "m.demir"),
                           ("On Monday the user w.anderson visited.", "w.anderson"),
                           ("Send it to my user name, m.singh.", "m.singh")):
            self.assertUser(text, user)

    def test_shaped_like_a_login(self):
        for text, user in (("Welcome back, Nimali.Sivagnanam.", "Nimali.Sivagnanam"),
                           ("Feedback from Samuel1995 was kind.", "Samuel1995"),
                           ("Please contact k.williams about it.", "k.williams"),
                           ("Find it on my SomchaiHoang page.", "SomchaiHoang"),
                           ("Then Brent_ShadowHunter joined.", "Brent_ShadowHunter")):
            self.assertUser(text, user)

    def test_a_login_as_the_speaker(self):
        self.assertEqual(plain("Host: Welcome.\npmarler: Sure, thanks.\n"),
                         "Host: Welcome.\n[username 1]: Sure, thanks.\n")

    def test_ordinary_words_stay(self):
        for text in ("The user experience was good.", "The login was successful.",
                     "See Fig.Three below.", "TikTok posts.",
                     "Open a.out now.",
                     "note: bring pens", "tldr: fine",
                     "Ask the user about it."):
            self.assertEqual(plain(text), text)


class EveryMention(unittest.TestCase):
    """The share preset numbers people, not tokens, so these check what is left."""

    def assertGone(self, text, *names, kept=()):
        out = plain(text)
        for name in names:
            self.assertNotIn(name, out.lower(), out)
        for words in kept:
            self.assertIn(words, out, out)
        return out

    def test_a_found_name_goes_wherever_it_appears(self):
        self.assertGone("ask okonkwo first. Then Dr Okonkwo rang, and OKONKWO wrote.", "okonkwo")

    def test_the_parts_of_a_name_go_too(self):
        self.assertGone("Mr Tendai Phiri came in. Later phiri rang about TENDAI.",
                        "phiri", "tendai")

    def test_possessives_keep_their_s(self):
        out = self.assertGone("Mr Phiri's bag. Then phiri's coat.", "phiri")
        self.assertEqual(out.count("'s "), 2, out)

    def test_a_part_that_is_a_word_stays_in_lower_case(self):
        self.assertGone("Mr Will Baker came. We will ask the baker. Will Baker left.",
                        "will baker", kept=("We will ask the baker.",))

    def test_core_too(self):
        out = core.TOKEN.sub("<T>", core.scrub("Dr Okonkwo rang. okonkwo again.")[0])
        self.assertEqual(out, "<T> rang. <T> again.")

    def test_restore_gives_back_each_mention(self):
        text = "Mr Tendai Phiri came. phiri's coat and PHIRI's hat, then tendai left."
        result = Hush("ask-ai").scrub(text)
        self.assertNotIn("phiri", result.text.lower())
        self.assertEqual(result.restore(result.text), text)

class ContextCues(unittest.TestCase):
    """A few phrases that say what comes next. Names here are invented words, so no list
    knows them and only the cue can find them."""

    def test_a_name_after_my_name_is(self):
        for text, name in (("my name is zorvath kellim and I need help", "zorvath kellim"),
                           ("my name's qwilleran.", "qwilleran"),
                           ("My name is Zorvath, thanks", "Zorvath"),
                           ("hi, this is zorvath speaking", "zorvath"),
                           ("you can call me zorvath.", "zorvath"),
                           ("Name: zorvath", "zorvath")):
            out = plain(text)
            self.assertNotIn(name.split()[0], out, text)
            self.assertIn("[person", out, text)

    def test_a_word_after_the_cue_stays(self):
        for text in ("call me back tomorrow", "my name is on the list", "call me when ready",
                     "this is fine", "you can call me later."):
            self.assertEqual(plain(text), text)

    def test_a_number_after_a_phone_cue_is_a_phone(self):
        for text in ("my number is 4471 2390", "call me on 4471 2390", "text me on 447 1239",
                     "you can reach me at 4471-2390"):
            self.assertIn("[phone 1]", plain(text), text)
        self.assertEqual(plain("call me on Monday"), "call me on Monday")

    def test_a_plate_after_its_label(self):
        self.assertEqual(plain("The licence plate KK 439 XY was seen."),
                         "The licence plate [code 1] was seen.")
        self.assertEqual(plain("license plate number: D AS 3512"),
                         "license plate number: [code 1]")


if __name__ == "__main__":
    unittest.main()
