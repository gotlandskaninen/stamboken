"""
Tests for the Bunny roster model, Individual.voided, and roster service functions.
"""

import threading
from datetime import date

import peewee
import utils.database as db
from blueprints.bunny_v2 import (
    RosterActionError,
    add_bunnies,
    delete_bunny,
    get_litter_roster,
    patch_bunny,
    promote_bunny,
    reorder_roster,
)
from utils.database import DATABASE

from tests.database_test import DatabaseTest
from tests.test_bunny_v2_api import paper_number_for


class TestBunnyModel(DatabaseTest):
    def _litter(self):
        return db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=6,
        )

    def test_defaults(self):
        bunny = db.Bunny.create(breeding=self._litter(), slot_order=1, observed_sex="female")
        assert bunny.fate == "undecided" and bunny.individual is None

    def test_registered_requires_link(self):
        bunny = db.Bunny.create(breeding=self._litter(), slot_order=1)
        bunny.fate = "registered"
        with self.assertRaises(peewee.IntegrityError):
            bunny.save()

    def test_as_dict_unlinked_and_linked(self):
        b = self._litter()
        bunny = db.Bunny.create(breeding=b, slot_order=1, observed_sex="male", observed_color="svart")
        assert bunny.as_dict()["observed_sex"] == "male" and "individual" not in bunny.as_dict()
        ind = db.Individual.create(number=f"{self.herds[0].herd}-3011", origin_herd=self.herds[0], breeding=b)
        bunny.individual = ind
        bunny.fate = "registered"
        bunny.save()
        assert bunny.as_dict()["individual"]["number"] == f"{self.herds[0].herd}-3011"

    def test_individual_voided_default(self):
        assert "voided" in db.Individual._meta.fields


class TestRosterService(DatabaseTest):
    def _litter(self):
        return db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2030, 3, 25),
            litter_number=1,
            litter_size=6,
        )

    def test_add_bunnies_single_slot_order(self):
        b = self._litter()
        bunnies = add_bunnies(b, count=1, observed_sex="female")
        assert len(bunnies) == 1
        assert bunnies[0].slot_order == 1
        assert bunnies[0].observed_sex == "female"

    def test_add_bunnies_bulk_sequential_slots(self):
        b = self._litter()
        bunnies = add_bunnies(b, count=3)
        assert [bun.slot_order for bun in bunnies] == [1, 2, 3]

    def test_add_bunnies_appends_after_existing(self):
        b = self._litter()
        add_bunnies(b, count=2)
        more = add_bunnies(b, count=2)
        assert [bun.slot_order for bun in more] == [3, 4]

    def test_reorder_renormalises(self):
        b = self._litter()
        bunnies = add_bunnies(b, count=3)
        ids = [bun.id for bun in bunnies]
        reorder_roster(b, [ids[2], ids[0], ids[1]])
        refreshed = list(db.Bunny.select().where(db.Bunny.breeding == b).order_by(db.Bunny.slot_order))
        assert [r.id for r in refreshed] == [bunnies[2].id, bunnies[0].id, bunnies[1].id]
        assert [r.slot_order for r in refreshed] == [1, 2, 3]

    def test_reorder_wrong_ids_raises(self):
        b = self._litter()
        bunnies = add_bunnies(b, count=2)
        with self.assertRaises(ValueError):
            reorder_roster(b, [bunnies[0].id, 99999])

    def test_patch_bunny_updates_field(self):
        b = self._litter()
        bunny = add_bunnies(b, count=1)[0]
        patch_bunny(bunny, observed_sex="male")
        assert db.Bunny.get_by_id(bunny.id).observed_sex == "male"

    def test_patch_bunny_rejects_registered_fate(self):
        b = self._litter()
        bunny = add_bunnies(b, count=1)[0]
        with self.assertRaises(ValueError):
            patch_bunny(bunny, fate="registered")

    def test_patch_bunny_rejects_unknown_fate(self):
        b = self._litter()
        bunny = add_bunnies(b, count=1)[0]
        with self.assertRaises(ValueError):
            patch_bunny(bunny, fate="invented")

    def test_patch_bunny_accepts_valid_fates(self):
        b = self._litter()
        for fate in ("undecided", "kept_unregistered", "sold_unregistered", "culled", "died"):
            bunny = add_bunnies(b, count=1)[0]
            patch_bunny(bunny, fate=fate)
            assert db.Bunny.get_by_id(bunny.id).fate == fate

    def test_delete_bunny_works_unlinked(self):
        b = self._litter()
        bunny = add_bunnies(b, count=1)[0]
        bunny_id = bunny.id
        delete_bunny(bunny)
        assert not db.Bunny.select().where(db.Bunny.id == bunny_id).exists()

    def test_delete_bunny_blocked_when_linked(self):
        b = self._litter()
        bunny = add_bunnies(b, count=1)[0]
        ind = db.Individual.create(
            number=f"{self.herds[0].herd}-3051",
            origin_herd=self.herds[0],
            breeding=b,
        )
        bunny.individual = ind
        bunny.fate = "registered"
        bunny.save()
        with self.assertRaises(ValueError):
            delete_bunny(bunny)

    def test_get_roster_includes_provisional_number_for_unlinked(self):
        b = self._litter()
        add_bunnies(b, count=1)
        roster = get_litter_roster(b)
        assert len(roster) == 1
        assert "provisional_number" in roster[0]
        assert roster[0]["provisional_number"] is not None

    def test_get_roster_no_provisional_for_linked(self):
        b = self._litter()
        bunny = add_bunnies(b, count=1)[0]
        ind = db.Individual.create(
            number=f"{self.herds[0].herd}-3052",
            origin_herd=self.herds[0],
            breeding=b,
        )
        bunny.individual = ind
        bunny.fate = "registered"
        bunny.save()
        roster = get_litter_roster(b)
        assert "provisional_number" not in roster[0]
        assert "individual" in roster[0]

    def test_get_roster_ordered_by_slot_order(self):
        b = self._litter()
        bunnies = add_bunnies(b, count=3)
        ids = [bun.id for bun in bunnies]
        reorder_roster(b, [ids[2], ids[0], ids[1]])
        roster = get_litter_roster(b)
        assert roster[0]["id"] == bunnies[2].id
        assert roster[1]["id"] == bunnies[0].id


class TestKeptUnregisteredNotAKeeper(DatabaseTest):
    """M3: kept_unregistered bunnies must not block promote order or reserve a slot."""

    def _litter(self):
        return db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),  # old enough
            litter_number=1,
            litter_size=6,
            litter_size6w=6,  # a promote issues a certificate
        )

    def test_unregistered_fates_do_not_block_higher_slot_promote(self):
        """A slot_1 kept_/sold_unregistered must NOT cause a 409 when promoting slot_2."""
        self._check_promote_slot2("kept_unregistered")

    def test_sold_unregistered_does_not_block_higher_slot_promote(self):
        """Same as kept_unregistered: sold_unregistered is a non-keeper fate."""
        self._check_promote_slot2("sold_unregistered")

    def _check_promote_slot2(self, fate):
        litter = self._litter()
        db.Bunny.create(breeding=litter, slot_order=1, fate=fate)
        b2 = db.Bunny.create(breeding=litter, slot_order=2, observed_sex="female", observed_color="bleighe")
        ind, _cert, _err = promote_bunny(
            b2.id,
            user=self.admin,
            user_id=self.admin.uuid,
            certificate_type="paper",
            paper_certificate="PAP-1",
            paper_number=paper_number_for(b2.id),
        )
        self.assertEqual(ind.number, f"{self.herds[0].herd}-2511")

    def test_kept_unregistered_does_not_consume_provisional_slot(self):
        """slot_1 kept_unregistered → slot_2 provisional must be prefix+1, not prefix+2."""
        from utils.individual_number_v2 import provisional_number

        litter = self._litter()
        db.Bunny.create(breeding=litter, slot_order=1, fate="kept_unregistered")
        b2 = db.Bunny.create(breeding=litter, slot_order=2)
        prov = provisional_number(litter, b2)
        self.assertEqual(prov, f"{self.herds[0].herd}-2511")


class TestPromoteConcurrency(DatabaseTest):
    """Parallel promotes in one litter serialise under FOR UPDATE."""

    def test_for_update_serialises_promote_no_slot_collision(self):
        # Historical-year litter (no current-year conflict gate), old enough.
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=6,
            litter_size6w=6,  # a promote issues a certificate
        )
        b1 = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        b2 = db.Bunny.create(breeding=litter, slot_order=2, observed_sex="male", observed_color="bleighe")
        admin = self.admin

        barrier = threading.Barrier(2)
        results = {}
        errors = {}

        papers = {b1.id: paper_number_for(b1.id), b2.id: paper_number_for(b2.id)}

        def worker(bunny_id, key):
            try:
                DATABASE.connect(reuse_if_open=True)
                barrier.wait()  # maximise contention on the FOR UPDATE
                ind, _cert, _err = promote_bunny(
                    bunny_id,
                    user=admin,
                    user_id=admin.uuid,
                    certificate_type="paper",
                    paper_certificate=f"PAP-{key}",
                    paper_number=papers[bunny_id],
                )
                results[key] = ind.number
            except RosterActionError as exc:
                errors[key] = exc.status
            except Exception as exc:  # noqa: BLE001 — surface unexpected races
                errors[key] = repr(exc)
            finally:
                try:
                    DATABASE.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=worker, args=(b1.id, "a"))
        t2 = threading.Thread(target=worker, args=(b2.id, "b"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Any failure must be a clean out-of-order 409 — never a collision/500.
        for key, status in errors.items():
            assert status == 409, f"worker {key} raised unexpected {status!r}"

        # The lock serialised the slot space: every minted number is distinct.
        minted = list(results.values())
        assert len(minted) == len(set(minted)), f"slot collision: {minted}"
        assert len(results) >= 1  # at least one promote went through

        # The DB matches: one Individual per success, all with distinct numbers.
        inds = list(db.Individual.select().where(db.Individual.breeding == litter))
        assert len(inds) == len(results)
        assert len({i.number for i in inds}) == len(inds)
        assert all(i.number in ("G1-2511", "G1-2512") for i in inds)
