"""Tests for v2 individual number helpers.

isort:skip_file
"""

import os
from datetime import date, datetime, timedelta

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from utils.individual_number_v2 import (  # noqa: E402
    _create_individual_record,
    _get_litter_state,
    check_litter_order,
    generate_individual_number,
    provisional_number,
    renumber_litters,
    suggest_individual_number,
    suggest_litter_number,
    validate_certificate_allowed,
    validate_first_certificate,
)

from tests.database_test import DatabaseTest  # noqa: E402


class TestSuggestLitterNumber(DatabaseTest):
    """Tests for suggest_litter_number()."""

    def test_first_litter_of_year(self):
        """First litter in a year gets number 1."""
        herd = self.herds[0]
        result = suggest_litter_number(herd.herd, date(2030, 3, 25))
        self.assertEqual(result["suggested"], 1)
        self.assertEqual(result["conflicts"], [])

    def test_second_litter_chronological(self):
        """Adding a later litter gets the next number."""
        herd = self.herds[0]
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 2, 10),
            litter_number=1,
            litter_size=3,
        )
        result = suggest_litter_number(herd.herd, date(2030, 5, 15))
        self.assertEqual(result["suggested"], 2)
        self.assertEqual(result["conflicts"], [])

    def test_earlier_litter_detects_conflict(self):
        """Adding an earlier litter detects existing conflict."""
        herd = self.herds[0]
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 2),
            litter_number=1,
            litter_size=3,
        )
        result = suggest_litter_number(herd.herd, date(2030, 2, 1))
        self.assertEqual(result["suggested"], 1)
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["conflicts"][0]["current_litter_number"], 1)
        self.assertEqual(result["conflicts"][0]["suggested_litter_number"], 2)

    def test_different_year_independent(self):
        """Litters in different years don't affect each other."""
        herd = self.herds[0]
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2029, 6, 1),
            litter_number=1,
            litter_size=3,
        )
        result = suggest_litter_number(herd.herd, date(2030, 1, 15))
        self.assertEqual(result["suggested"], 1)


class TestGenerateIndividualNumber(DatabaseTest):
    """Tests for generate_individual_number()."""

    def test_first_rabbit_in_litter(self):
        """First rabbit gets position 1."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=5,
        )
        number = generate_individual_number(herd.herd, b)
        self.assertEqual(number, f"{herd.herd}-3011")

    def test_second_rabbit_in_litter(self):
        """Second rabbit gets position 2."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=5,
        )
        db.Individual.create(
            number=f"{herd.herd}-3011",
            origin_herd=herd,
            breeding=b,
            sex="female",
        )
        number = generate_individual_number(herd.herd, b)
        self.assertEqual(number, f"{herd.herd}-3012")

    def test_nine_rabbit_ceiling(self):
        """Cannot add more than 9 rabbits to a litter."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=10,
        )
        for i in range(1, 10):
            db.Individual.create(
                number=f"{herd.herd}-301{i}",
                origin_herd=herd,
                breeding=b,
                sex="female",
            )
        with self.assertRaises(ValueError):
            generate_individual_number(herd.herd, b)

    def test_no_litter_number_raises(self):
        """Breeding without litter_number raises ValueError."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_size=5,
        )
        with self.assertRaises(ValueError):
            generate_individual_number(herd.herd, b)

    def test_litter_size_validation(self):
        """Cannot add more rabbits than litter_size allows."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=2,
        )
        db.Individual.create(
            number=f"{herd.herd}-3011",
            origin_herd=herd,
            breeding=b,
            sex="female",
        )
        db.Individual.create(
            number=f"{herd.herd}-3012",
            origin_herd=herd,
            breeding=b,
            sex="male",
        )
        with self.assertRaises(ValueError):
            generate_individual_number(herd.herd, b)


class TestCheckLitterOrder(DatabaseTest):
    """Tests for check_litter_order()."""

    def test_consistent_returns_true(self):
        """No conflicts when litters are in order."""
        herd = self.herds[0]
        db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 2, 1), litter_number=1, litter_size=3)
        db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=2, litter_size=4)
        result = check_litter_order(herd.herd, 2030)
        self.assertTrue(result["consistent"])
        self.assertEqual(result["conflicts"], [])

    def test_inconsistent_detects_conflict(self):
        """Detects when litter numbers don't match birth order."""
        herd = self.herds[0]
        db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=1, litter_size=3)
        db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 2, 1), litter_number=2, litter_size=4)
        result = check_litter_order(herd.herd, 2030)
        self.assertFalse(result["consistent"])
        self.assertEqual(len(result["conflicts"]), 2)


class TestRenumberLitters(DatabaseTest):
    """Tests for renumber_litters()."""

    def test_renumber_fixes_order(self):
        """Renumbering assigns correct chronological order."""
        herd = self.herds[0]
        b1 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=1, litter_size=3)
        b2 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 2, 1), litter_number=2, litter_size=4)
        renumber_litters(herd.herd, 2030, confirm=True)
        b1_refreshed = db.Breeding.get_by_id(b1.id)
        b2_refreshed = db.Breeding.get_by_id(b2.id)
        self.assertEqual(b2_refreshed.litter_number, 1)  # Feb is first
        self.assertEqual(b1_refreshed.litter_number, 2)  # May is second

    def test_renumber_updates_individual_numbers(self):
        """Renumbering cascades to individual numbers."""
        herd = self.herds[0]
        b1 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=1, litter_size=3)
        ind = db.Individual.create(
            number=f"{herd.herd}-3011",
            origin_herd=herd,
            breeding=b1,
            sex="female",
        )
        db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 2, 1), litter_number=2, litter_size=4)
        renumber_litters(herd.herd, 2030, confirm=True)
        ind_refreshed = db.Individual.get_by_id(ind.id)
        # Was litter 1 pos 1, now litter 2 pos 1
        self.assertEqual(ind_refreshed.number, f"{herd.herd}-3021")

    def test_dry_run_returns_preview(self):
        """Dry run shows changes without applying them."""
        herd = self.herds[0]
        b1 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=1, litter_size=3)
        renumber_litters(herd.herd, 2030, confirm=False)
        b1_check = db.Breeding.get_by_id(b1.id)
        self.assertEqual(b1_check.litter_number, 1)  # Unchanged


class TestSuggestIndividualNumber(DatabaseTest):
    """Tests for suggest_individual_number()."""

    def test_empty_litter(self):
        """Empty litter suggests position 1, all 9 available."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=5,
        )
        result = suggest_individual_number(herd.herd, b)
        self.assertEqual(result["suggested"], f"{herd.herd}-3011")
        self.assertEqual(result["suggested_position"], 1)
        self.assertEqual(result["used_positions"], [])
        self.assertEqual(result["available_positions"], [1, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertEqual(result["current_count"], 0)
        self.assertEqual(result["max_count"], 5)
        self.assertEqual(result["limited_by"], "litter_size")
        self.assertTrue(result["can_register"])

    def test_with_used_positions(self):
        """Used positions are excluded from available, suggested is lowest free."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=9,
        )
        # User registered out-of-order: positions 1 and 3
        for pos in (1, 3):
            db.Individual.create(
                number=f"{herd.herd}-301{pos}",
                origin_herd=herd,
                breeding=b,
                sex="female",
            )
        result = suggest_individual_number(herd.herd, b)
        self.assertEqual(result["suggested_position"], 2)
        self.assertEqual(result["used_positions"], [1, 3])
        self.assertEqual(result["available_positions"], [2, 4, 5, 6, 7, 8, 9])
        self.assertEqual(result["current_count"], 2)

    def test_litter_full_cannot_register(self):
        """When max_count reached, can_register=False and suggested=None."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=2,
        )
        for pos in (1, 2):
            db.Individual.create(
                number=f"{herd.herd}-301{pos}",
                origin_herd=herd,
                breeding=b,
                sex="female",
            )
        result = suggest_individual_number(herd.herd, b)
        self.assertFalse(result["can_register"])
        self.assertIsNone(result["suggested"])
        self.assertIsNone(result["suggested_position"])
        self.assertEqual(result["limited_by"], "litter_size")


class TestGenerateWithExplicitPosition(DatabaseTest):
    """Tests for generate_individual_number() with explicit position."""

    def test_explicit_position_succeeds(self):
        """Caller can pick a specific available position."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=9,
        )
        number = generate_individual_number(herd.herd, b, position=7)
        self.assertEqual(number, f"{herd.herd}-3017")

    def test_explicit_position_taken_raises(self):
        """Explicit position already in use raises ValueError."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=9,
        )
        db.Individual.create(
            number=f"{herd.herd}-3013",
            origin_herd=herd,
            breeding=b,
            sex="female",
        )
        with self.assertRaises(ValueError) as ctx:
            generate_individual_number(herd.herd, b, position=3)
        self.assertEqual(str(ctx.exception), "position_taken")

    def test_explicit_position_out_of_range(self):
        """Position outside 1-9 raises."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=9,
        )
        with self.assertRaises(ValueError) as ctx:
            generate_individual_number(herd.herd, b, position=10)
        self.assertEqual(str(ctx.exception), "position_out_of_range")
        with self.assertRaises(ValueError) as ctx2:
            generate_individual_number(herd.herd, b, position=0)
        self.assertEqual(str(ctx2.exception), "position_out_of_range")


class TestRegistrationIsSeparateFromCertificate(DatabaseTest):
    """Registration is now decoupled from certificate eligibility.

    Registration is allowed up to min(9, litter_size), regardless of 6w.
    Certificate issuance has its own quota (litter_size6w when past 6w).
    """

    def test_registration_allowed_past_6w_beyond_size6w(self):
        """Past 6w with 2 already registered and litter_size6w=2 — can still register 3rd (tracking)."""
        herd = self.herds[0]
        old_birth = date.today() - timedelta(days=50)
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=old_birth,
            litter_number=1,
            litter_size=9,
            litter_size6w=2,
        )
        year_suffix = str(old_birth.year)[2:4]
        for pos in (1, 2):
            db.Individual.create(
                number=f"{herd.herd}-{year_suffix}1{pos}",
                origin_herd=herd,
                breeding=b,
                sex="female",
            )
        number = generate_individual_number(herd.herd, b)
        self.assertEqual(number, f"{herd.herd}-{year_suffix}13")

    def test_suggest_exposes_certificate_quota(self):
        """suggest returns certified_count, certified_max_count, past_6w, can_issue_certificate."""
        herd = self.herds[0]
        old_birth = date.today() - timedelta(days=50)
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=old_birth,
            litter_number=1,
            litter_size=9,
            litter_size6w=3,
        )
        result = suggest_individual_number(herd.herd, b)
        self.assertEqual(result["max_count"], 9)
        self.assertEqual(result["limited_by"], "ceiling")
        self.assertEqual(result["certified_max_count"], 3)
        self.assertEqual(result["certified_count"], 0)
        self.assertTrue(result["past_6w"])
        self.assertTrue(result["can_issue_certificate"])

    def test_suggest_litter_size6w_null_past_6w_blocks_certificate(self):
        """Past 6w + litter_size6w null → can_issue_certificate=False with litter_size6w_required."""
        herd = self.herds[0]
        old_birth = date.today() - timedelta(days=50)
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=old_birth,
            litter_number=1,
            litter_size=9,
        )
        result = suggest_individual_number(herd.herd, b)
        self.assertEqual(result["max_count"], 9)
        self.assertEqual(result["limited_by"], "ceiling")
        self.assertIsNone(result["certified_max_count"])
        self.assertTrue(result["past_6w"])
        self.assertFalse(result["can_issue_certificate"])
        self.assertEqual(result["certificate_blocked_reason"], "litter_size6w_required")

    def test_suggest_before_6w_allows_certificate_regardless(self):
        """Before 6w: no cert quota enforced, can_issue_certificate=True."""
        herd = self.herds[0]
        recent_birth = date.today() - timedelta(days=10)
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=recent_birth,
            litter_number=1,
            litter_size=9,
            # litter_size6w intentionally None
        )
        result = suggest_individual_number(herd.herd, b)
        self.assertFalse(result["past_6w"])
        self.assertTrue(result["can_issue_certificate"])
        self.assertIsNone(result["certified_max_count"])


class TestValidateCertificateAllowed(DatabaseTest):
    """Tests for validate_certificate_allowed() — the enforcement gate on POST."""

    def test_noop_before_6w(self):
        """Before 6w the function does nothing (no cert cap enforced)."""
        herd = self.herds[0]
        recent_birth = date.today() - timedelta(days=10)
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=recent_birth,
            litter_number=1,
            litter_size=9,
        )
        # Should not raise even with litter_size6w null
        validate_certificate_allowed(herd.herd, b)

    def test_raises_when_litter_size6w_null_past_6w(self):
        """Past 6w + litter_size6w null → raises litter_size6w_required."""
        herd = self.herds[0]
        old_birth = date.today() - timedelta(days=50)
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=old_birth,
            litter_number=1,
            litter_size=9,
        )
        with self.assertRaises(ValueError) as ctx:
            validate_certificate_allowed(herd.herd, b)
        self.assertEqual(str(ctx.exception), "litter_size6w_required")

    def test_raises_when_cert_quota_exceeded(self):
        """Past 6w + certified already equals litter_size6w → raises certificate_quota_exceeded."""
        herd = self.herds[0]
        old_birth = date.today() - timedelta(days=50)
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=old_birth,
            litter_number=1,
            litter_size=9,
            litter_size6w=2,
        )
        year_suffix = str(old_birth.year)[2:4]
        # 2 certified rabbits already — quota full
        for pos in (1, 2):
            db.Individual.create(
                number=f"{herd.herd}-{year_suffix}1{pos}",
                origin_herd=herd,
                breeding=b,
                sex="female",
                certificate=f"CERT-{pos}",
            )
        with self.assertRaises(ValueError) as ctx:
            validate_certificate_allowed(herd.herd, b)
        self.assertEqual(str(ctx.exception), "certificate_quota_exceeded")

    def test_allows_when_uncertified_tracked_rabbits_exist(self):
        """Tracked rabbits without certificates don't count toward quota."""
        herd = self.herds[0]
        old_birth = date.today() - timedelta(days=50)
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=old_birth,
            litter_number=1,
            litter_size=9,
            litter_size6w=2,
        )
        year_suffix = str(old_birth.year)[2:4]
        # 3 tracked, none certified
        for pos in (1, 2, 3):
            db.Individual.create(
                number=f"{herd.herd}-{year_suffix}1{pos}",
                origin_herd=herd,
                breeding=b,
                sex="female",
                # no certificate set
            )
        # Certificate still allowed — quota is 2 and 0 certified
        validate_certificate_allowed(herd.herd, b)

    def test_counts_digital_certificates_toward_quota(self):
        """Both paper (certificate) and digital_certificate count toward the quota."""
        herd = self.herds[0]
        old_birth = date.today() - timedelta(days=50)
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=old_birth,
            litter_number=1,
            litter_size=9,
            litter_size6w=1,
        )
        year_suffix = str(old_birth.year)[2:4]
        # 1 digital cert rabbit — quota full
        db.Individual.create(
            number=f"{herd.herd}-{year_suffix}11",
            origin_herd=herd,
            breeding=b,
            sex="female",
            digital_certificate=1234,
        )
        with self.assertRaises(ValueError) as ctx:
            validate_certificate_allowed(herd.herd, b)
        self.assertEqual(str(ctx.exception), "certificate_quota_exceeded")


class TestValidateFirstCertificate(DatabaseTest):
    """validate_first_certificate(): litter_size6w is required and the roster must agree with it."""

    def _litter(self, **fields):
        return db.Breeding.create(
            breeding_herd_id=self.herds[0], birth_date=date(2025, 1, 10), litter_number=1, litter_size=6, **fields
        )

    def test_a_roster_litter_requires_litter_size6w(self):
        with self.assertRaises(ValueError) as ctx:
            validate_first_certificate(self._litter())
        self.assertEqual(str(ctx.exception), "litter_size6w_required")

    def test_a_pre_roster_litter_needs_no_litter_size6w(self):
        validate_first_certificate(db.Breeding.create(breeding_herd_id=self.herds[0], birth_date=date(2025, 1, 10)))

    def test_alive_kits_are_the_roster_rows_not_died_or_culled(self):
        """undecided, kept_unregistered and registered count as alive; died and culled do not."""
        litter = self._litter(litter_size6w=2)
        kit = db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2511")
        for slot, fate in enumerate(["undecided", "kept_unregistered", "registered", "died", "culled"], start=1):
            db.Bunny.create(
                breeding=litter, slot_order=slot, fate=fate, individual=kit if fate == "registered" else None
            )
        with self.assertRaises(ValueError) as ctx:
            validate_first_certificate(litter)
        self.assertEqual(str(ctx.exception), "roster_alive_exceeds_6w")
        self.assertEqual(ctx.exception.must_mark_dead, 1)

        db.Bunny.update(fate="died").where((db.Bunny.breeding == litter) & (db.Bunny.fate == "undecided")).execute()
        validate_first_certificate(litter)  # 2 alive, 2 alive at 6 weeks: in sync


class TestRetiredSlots(DatabaseTest):
    """Voided Individuals are excluded from the live count and their slot is retired."""

    def _litter(self, litter_size=9, litter_number=1, birth=date(2030, 3, 25)):
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=birth,
            litter_number=litter_number,
            litter_size=litter_size,
        )
        return herd, b

    def _voided(self, herd, breeding, pos):
        year_suffix = str(breeding.birth_date.year)[2:4]
        return db.Individual.create(
            number=f"{herd.herd}-{year_suffix}{breeding.litter_number}{pos}",
            origin_herd=herd,
            breeding=breeding,
            sex="female",
            voided=True,
            voided_at=datetime.now(),
        )

    def _live(self, herd, breeding, pos, **kwargs):
        year_suffix = str(breeding.birth_date.year)[2:4]
        return db.Individual.create(
            number=f"{herd.herd}-{year_suffix}{breeding.litter_number}{pos}",
            origin_herd=herd,
            breeding=breeding,
            sex="female",
            **kwargs,
        )

    def test_voided_excluded_from_live_count_and_tracked_as_retired(self):
        """A voided sibling drops out of used_positions/current_count and into retired_positions."""
        herd, b = self._litter(litter_size=9)
        self._live(herd, b, 1)
        self._voided(herd, b, 2)
        state = _get_litter_state(herd.herd, b)
        self.assertEqual(state["used_positions"], [1])
        self.assertEqual(state["retired_positions"], [2])
        self.assertEqual(state["current_count"], 1)
        self.assertNotIn(1, state["available_positions"])
        self.assertNotIn(2, state["available_positions"])
        self.assertEqual(state["available_positions"][0], 3)

    def test_retired_slot_never_reissued(self):
        """generate_individual_number skips a retired slot (never reuses it)."""
        herd, b = self._litter(litter_size=9)
        self._live(herd, b, 1)
        self._voided(herd, b, 2)
        number = generate_individual_number(herd.herd, b)
        self.assertEqual(number, f"{herd.herd}-3013")

    def test_retired_slot_counts_toward_cap(self):
        """used ∪ retired filling min(litter_size, 9) reaches the cap."""
        herd, b = self._litter(litter_size=2)
        self._live(herd, b, 1)  # live
        self._voided(herd, b, 2)  # retired
        with self.assertRaises(ValueError):
            generate_individual_number(herd.herd, b)

    def test_promote_unpromote_promote_does_not_reuse_retired_slot(self):
        """Simulated promote(1,2) → unpromote(1) → promote-new mints slot 3, not the retired 1."""
        herd, b = self._litter(litter_size=9)
        self._live(herd, b, 2)  # slot 2 still registered
        self._voided(herd, b, 1)  # slot 1 was promoted then unpromoted -> retired
        number = generate_individual_number(herd.herd, b)
        self.assertEqual(number, f"{herd.herd}-3013")

    def test_explicit_retired_position_rejected(self):
        """Picking a retired slot explicitly raises position_taken."""
        herd, b = self._litter(litter_size=9)
        self._voided(herd, b, 4)
        with self.assertRaises(ValueError) as ctx:
            generate_individual_number(herd.herd, b, position=4)
        self.assertEqual(str(ctx.exception), "position_taken")


class TestProvisionalNumber(DatabaseTest):
    """provisional_number() simulates order-constrained promotion; equals the minted slot."""

    def _litter(self, litter_size=9, litter_number=1, birth=date(2030, 3, 25)):
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=birth,
            litter_number=litter_number,
            litter_size=litter_size,
        )
        return herd, b

    def test_provisional_equals_minted_for_lowest_unpromoted(self):
        """The lowest-slot_order Bunny's provisional == generate_individual_number()."""
        herd, b = self._litter()
        bn1 = db.Bunny.create(breeding=b, slot_order=1)
        bn2 = db.Bunny.create(breeding=b, slot_order=2)
        minted = generate_individual_number(herd.herd, b)
        self.assertEqual(provisional_number(b, bn1), minted)
        self.assertEqual(provisional_number(b, bn1), f"{herd.herd}-3011")
        # The next Bunny in order takes the following free slot.
        self.assertEqual(provisional_number(b, bn2), f"{herd.herd}-3012")

    def test_provisional_equals_minted_after_retirement_gap(self):
        """After a retirement leaves a gap, provisional == minted == next free slot (not the gap)."""
        herd, b = self._litter()
        # slot 1 retired, slot 2 live -> available starts at 3
        db.Individual.create(
            number=f"{herd.herd}-3011",
            origin_herd=herd,
            breeding=b,
            sex="female",
            voided=True,
            voided_at=datetime.now(),
        )
        db.Individual.create(number=f"{herd.herd}-3012", origin_herd=herd, breeding=b, sex="female")
        bn = db.Bunny.create(breeding=b, slot_order=1)
        minted = generate_individual_number(herd.herd, b)
        self.assertEqual(provisional_number(b, bn), minted)
        self.assertEqual(provisional_number(b, bn), f"{herd.herd}-3013")

    def test_provisional_none_without_litter_number(self):
        """No confirmed litter_number -> no provisional number."""
        herd = self.herds[0]
        b = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 3, 25), litter_size=5)
        bn = db.Bunny.create(breeding=b, slot_order=1)
        self.assertIsNone(provisional_number(b, bn))

    def test_provisional_none_for_died_bunny(self):
        """A died/culled Bunny has no provisional number."""
        herd, b = self._litter()
        bn = db.Bunny.create(breeding=b, slot_order=1, fate="died")
        self.assertIsNone(provisional_number(b, bn))

    def test_provisional_none_for_unregistered_fates(self):
        """A kept_/sold_unregistered Bunny has no provisional number."""
        herd, b = self._litter()
        for slot, fate in enumerate(("kept_unregistered", "sold_unregistered"), start=1):
            bn = db.Bunny.create(breeding=b, slot_order=slot, fate=fate)
            self.assertIsNone(provisional_number(b, bn))

    def test_kept_unregistered_does_not_shift_provisional_of_later_bunny(self):
        """A low-slot kept_unregistered bunny must NOT consume a provisional slot.

        slot_1 = kept_unregistered (will never be promoted)
        slot_2 = undecided → provisional should be prefix+1, not prefix+2.
        """
        herd, b = self._litter()
        db.Bunny.create(breeding=b, slot_order=1, fate="kept_unregistered")
        bn2 = db.Bunny.create(breeding=b, slot_order=2, fate="undecided")
        prov = provisional_number(b, bn2)
        self.assertEqual(prov, f"{herd.herd}-3011")


class TestNextIndividualNumberStored(DatabaseTest):
    """Legacy next_individual_number reads the stored Breeding.litter_number."""

    def test_uses_stored_litter_number_over_computed_rank(self):
        """Stored litter_number wins over the chronological ROW_NUMBER rank."""
        herd = self.herds[0]
        # Only litter in 2030, but stored litter_number deliberately = 4 (rank would be 1).
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=4,
            litter_size=5,
        )
        result = db.next_individual_number(herd.herd, "2030-03-25", b.id)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["number"], f"{herd.herd}-3041")

    def test_falls_back_to_rank_when_litter_number_null(self):
        """A NULL stored litter_number falls back to the computed rank (=1 here)."""
        herd = self.herds[0]
        b = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 3, 25), litter_size=5)
        result = db.next_individual_number(herd.herd, "2030-03-25", b.id)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["number"], f"{herd.herd}-3011")

    def test_stored_path_skips_retired_slot(self):
        """Legacy mint via stored litter_number never reuses a retired (voided) slot."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=9,
        )
        db.Individual.create(
            number=f"{herd.herd}-3011",
            origin_herd=herd,
            breeding=b,
            sex="female",
            voided=True,
            voided_at=datetime.now(),
        )
        result = db.next_individual_number(herd.herd, "2030-03-25", b.id)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["number"], f"{herd.herd}-3012")


class TestRenumberMovesVoided(DatabaseTest):
    """Renumber moves voided Individuals WITH their breeding; the slot stays retired.

    A voided number must always reflect its breeding's current litter_number. Freezing it
    (the old "skip voided" behaviour) orphaned a stale ``…{old}X`` that a litter swapping into
    the old namespace could later collide with on a promote (unique-index IntegrityError).
    """

    def test_renumber_moves_voided_individuals(self):
        """A voided sibling's number tracks its breeding's new litter digit; its slot stays retired."""
        herd = self.herds[0]
        b1 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=1, litter_size=9)
        db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 2, 1), litter_number=2, litter_size=9)
        live = db.Individual.create(number=f"{herd.herd}-3011", origin_herd=herd, breeding=b1, sex="female")
        voided = db.Individual.create(
            number=f"{herd.herd}-3012",
            origin_herd=herd,
            breeding=b1,
            sex="female",
            voided=True,
            voided_at=datetime.now(),
        )
        renumber_litters(herd.herd, 2030, confirm=True)
        b1_ref = db.Breeding.get_by_id(b1.id)
        self.assertEqual(b1_ref.litter_number, 2)  # May is second
        # Live AND voided both move into the new litter-2 namespace.
        self.assertEqual(db.Individual.get_by_id(live.id).number, f"{herd.herd}-3021")
        self.assertEqual(db.Individual.get_by_id(voided.id).number, f"{herd.herd}-3022")
        # The voided slot stays retired in the new namespace: a subsequent mint skips pos 2.
        state = _get_litter_state(herd.herd, b1_ref)
        self.assertIn(2, state["retired_positions"])
        self.assertEqual(generate_individual_number(herd.herd, b1_ref), f"{herd.herd}-3023")

    def test_renumber_swap_then_promote_no_collision(self):
        """Regression: renumber swaps two litters where the moving litter has a voided slot;
        promoting into the swapped-in litter mints the freed slot with NO IntegrityError."""
        herd = self.herds[0]
        # A: May, litter 1, with a voided individual at pos 1.
        a = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=1, litter_size=9)
        db.Individual.create(
            number=f"{herd.herd}-3011",
            origin_herd=herd,
            breeding=a,
            sex="female",
            voided=True,
            voided_at=datetime.now(),
        )
        # B: Feb, litter 2 (out of order) — renumber swaps it into litter 1.
        b = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 2, 1), litter_number=2, litter_size=9)
        renumber_litters(herd.herd, 2030, confirm=True)
        a_ref = db.Breeding.get_by_id(a.id)
        b_ref = db.Breeding.get_by_id(b.id)
        self.assertEqual(b_ref.litter_number, 1)  # Feb first
        self.assertEqual(a_ref.litter_number, 2)  # May second
        # The voided individual moved into A's new litter-2 namespace, freeing G1-3011.
        moved = db.Individual.get(db.Individual.breeding == a)
        self.assertEqual(moved.number, f"{herd.herd}-3021")
        # Promote into B (now litter 1): mints the slot the voided row vacated.
        minted = generate_individual_number(herd.herd, b_ref)
        self.assertEqual(minted, f"{herd.herd}-3011")
        # Persist it to prove the unique index does NOT reject (the bug raised IntegrityError here).
        db.Individual.create(number=minted, origin_herd=herd, breeding=b_ref, sex="female")
        self.assertTrue(db.Individual.select().where(db.Individual.number == minted).exists())


class TestHistoricalConflictGrandfathered(DatabaseTest):
    """Only current-year conflicts block; historical years are grandfathered."""

    def test_historical_conflict_does_not_block_minting(self):
        """An out-of-order historical litter still mints individual numbers."""
        herd = self.herds[0]
        b1 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2015, 5, 1), litter_number=1, litter_size=9)
        db.Breeding.create(breeding_herd_id=herd, birth_date=date(2015, 2, 1), litter_number=2, litter_size=9)
        order = check_litter_order(herd.herd, 2015)
        self.assertFalse(order["consistent"])  # a conflict exists for the historical year
        number = generate_individual_number(herd.herd, b1)
        self.assertEqual(number, f"{herd.herd}-1511")


class TestRegisterBirthAssignsLitterNumber(DatabaseTest):
    """register_birth assigns Breeding.litter_number, making the litter promotable."""

    def test_register_birth_assigns_litter_number_and_is_promotable(self):
        """A freshly birth-registered litter gets a litter_number and can mint numbers."""
        herd = self.herds[0]
        b = db.Breeding.create(breeding_herd_id=herd)  # no dates, no litter_number yet
        form = {"id": b.id, "date": "2024-04-15", "litter_size": 4}
        result = da.register_birth(form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["litter_number"], 1)
        refreshed = db.Breeding.get_by_id(b.id)
        self.assertEqual(refreshed.litter_number, 1)
        # Promotable: generate requires a non-null litter_number + birth_date.
        number = generate_individual_number(herd.herd, refreshed)
        self.assertEqual(number, f"{herd.herd}-2411")

    def test_sequential_births_get_distinct_litter_numbers(self):
        """Fix 1: two sequential births in the same herd/year get distinct litter_numbers."""
        herd = self.herds[0]
        b_feb = db.Breeding.create(breeding_herd_id=herd)
        b_may = db.Breeding.create(breeding_herd_id=herd)
        r1 = da.register_birth({"id": b_feb.id, "date": "2024-02-01", "litter_size": 4}, self.admin.uuid)
        r2 = da.register_birth({"id": b_may.id, "date": "2024-05-01", "litter_size": 4}, self.admin.uuid)
        self.assertEqual(r1["litter_number"], 1)
        self.assertEqual(r2["litter_number"], 2)  # chronological, distinct
        self.assertNotEqual(r1["litter_number"], r2["litter_number"])
        # No conflict surfaced for the in-order pair.
        self.assertNotIn("litter_number_conflicts", r1)
        self.assertNotIn("litter_number_conflicts", r2)

    def test_out_of_order_birth_registers_and_surfaces_conflict(self):
        """Fix 1: a later out-of-order birth still registers (appended) and surfaces the conflict."""
        herd = self.herds[0]
        b_feb = db.Breeding.create(breeding_herd_id=herd)
        b_may = db.Breeding.create(breeding_herd_id=herd)
        b_mar = db.Breeding.create(breeding_herd_id=herd)
        da.register_birth({"id": b_feb.id, "date": "2025-02-01", "litter_size": 4}, self.admin.uuid)  # -> 1
        da.register_birth({"id": b_may.id, "date": "2025-05-01", "litter_size": 4}, self.admin.uuid)  # -> 2
        # March is chronologically 2nd, but slot 2 is taken -> append max+1 = 3, conflict surfaced.
        r3 = da.register_birth({"id": b_mar.id, "date": "2025-03-01", "litter_size": 4}, self.admin.uuid)
        self.assertEqual(r3["status"], "success")
        self.assertEqual(r3["litter_number"], 3)
        self.assertIn("litter_number_conflicts", r3)
        # All three distinct, all persisted.
        numbers = {db.Breeding.get_by_id(b.id).litter_number for b in (b_feb, b_may, b_mar)}
        self.assertEqual(numbers, {1, 2, 3})


class TestCreateIndividualRecord(DatabaseTest):
    """Unit tests for _create_individual_record helper."""

    def _breeding(self, litter_number=1, litter_size=5, birth=date(2030, 3, 25)):
        return db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=birth,
            litter_number=litter_number,
            litter_size=litter_size,
        )

    def test_mints_smallest_free_number(self):
        """Helper mints the lowest available individual number inside an atomic block."""
        herd = self.herds[0]
        b = self._breeding()
        with db.DATABASE.atomic():
            ind = _create_individual_record(herd, b, signature=self.admin)
        self.assertEqual(ind.number, f"{herd.herd}-3011")
        self.assertTrue(db.Individual.select().where(db.Individual.id == ind.id).exists())

    def test_mints_next_free_when_first_slot_taken(self):
        """Helper skips occupied positions and mints the next free slot."""
        herd = self.herds[0]
        b = self._breeding()
        db.Individual.create(number=f"{herd.herd}-3011", origin_herd=herd, breeding=b, sex="female")
        with db.DATABASE.atomic():
            ind = _create_individual_record(herd, b, signature=self.admin)
        self.assertEqual(ind.number, f"{herd.herd}-3012")

    def test_creates_herd_tracking(self):
        """Helper creates exactly one HerdTracking entry for the new individual."""
        herd = self.herds[0]
        b = self._breeding()
        with db.DATABASE.atomic():
            ind = _create_individual_record(herd, b, signature=self.admin)
        ht_count = db.HerdTracking.select().where(db.HerdTracking.individual == ind).count()
        self.assertEqual(ht_count, 1)

    def test_sets_paper_certificate_when_given(self):
        """Helper stores paper certificate number when paper_certificate is given."""
        herd = self.herds[0]
        b = self._breeding()
        with db.DATABASE.atomic():
            ind = _create_individual_record(herd, b, paper_certificate="GK-TEST-999", signature=self.admin)
        refreshed = db.Individual.get_by_id(ind.id)
        self.assertEqual(refreshed.certificate, "GK-TEST-999")

    def test_no_certificate_when_paper_certificate_is_none(self):
        """Helper leaves certificate unset when paper_certificate is None."""
        herd = self.herds[0]
        b = self._breeding()
        with db.DATABASE.atomic():
            ind = _create_individual_record(herd, b, paper_certificate=None, signature=self.admin)
        refreshed = db.Individual.get_by_id(ind.id)
        self.assertIsNone(refreshed.certificate)

    def test_resolves_color_by_name(self):
        """Helper sets color when a matching Color exists in the herd's genebank."""
        herd = self.herds[0]
        b = self._breeding()
        with db.DATABASE.atomic():
            ind = _create_individual_record(herd, b, color="bleighe", signature=self.admin)
        refreshed = db.Individual.get_by_id(ind.id)
        self.assertIsNotNone(refreshed.color)

    def test_unknown_color_silently_skipped(self):
        """Helper silently ignores a color name that does not exist in the genebank."""
        herd = self.herds[0]
        b = self._breeding()
        with db.DATABASE.atomic():
            ind = _create_individual_record(herd, b, color="does-not-exist", signature=self.admin)
        refreshed = db.Individual.get_by_id(ind.id)
        self.assertIsNone(refreshed.color)
