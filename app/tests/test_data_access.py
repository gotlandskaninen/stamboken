#!/usr/bin/env python3
"""
Unit tests for the herdbook endpoints.

isort:skip_file
"""
# Fairly lax pylint settings as we want to test a lot of things

# pylint: disable=too-many-public-methods
# pylint: disable=too-many-statements

from copy import copy
from datetime import datetime, timedelta
from unittest import mock

import utils.data_access as da
from werkzeug.security import check_password_hash

# Valid UUID format that doesn't exist (PostgreSQL requires valid UUID syntax)
NONEXISTENT_UUID = "00000000-0000-0000-0000-000000000000"

import utils.database as db  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import herd_members, ht_row  # noqa: E402


class TestDataAccess(DatabaseTest):
    """
    Checks that data access functions return the correct data.
    """

    # Uncoment to get max diff
    # maxDiff = None

    def test_add_user(self):
        """
        Checks that `utils.data_access.get_colors` is working as intended.
        """
        valid_form = {
            "email": "test@user.example.com",
            "username": "test",
            "validated": True,
            "password": "pass",
        }
        no_email = copy(valid_form)
        del no_email["email"]
        no_pass = copy(valid_form)
        del no_pass["password"]

        self.assertDictEqual(da.add_user(valid_form, None), {"status": "error", "message": "forbidden"})
        self.assertDictEqual(
            da.add_user(valid_form, self.owner.uuid),
            {"status": "error", "message": "forbidden"},
        )
        self.assertDictEqual(
            da.add_user(valid_form, self.viewer.uuid),
            {"status": "error", "message": "forbidden"},
        )

        self.assertDictEqual(
            da.add_user(no_email, self.admin.uuid),
            {"status": "error", "message": "missing data"},
        )
        self.assertDictEqual(
            da.add_user(no_pass, self.admin.uuid),
            {"status": "error", "message": "missing data"},
        )

        result = da.add_user(valid_form, self.manager.uuid)
        self.assertEqual(result["status"], "created")

        self.assertDictEqual(
            da.add_user(valid_form, self.admin.uuid),
            {"status": "error", "message": "already exists"},
        )

    def test_register_user(self):
        """
        Checks that `utils.data_access.register_user` is working as intended.
        """
        email = "test_user@site"
        password = "pass"
        username = "test user"
        validated = True
        privileges = [{"level": "owner", "herd": self.herds[0].herd}]

        user = da.register_user(email, password, username, validated, privileges)

        self.assertEqual(user.email, email)
        self.assertEqual(user.username, username)
        self.assertEqual(user.validated, validated)
        self.assertEqual(user.privileges, privileges)

        auth = (
            db.Authenticators.select()
            .where((db.Authenticators.user == user.id) & (db.Authenticators.auth == "password"))
            .get()
        )
        self.assertTrue(check_password_hash(auth.auth_data, password))

    def test_authenticate_user(self):
        """
        Checks that `utils.data_access.authenticate_user` is working as intended.
        """
        email = "test_authenticate"
        password = "pass"

        da.register_user(email, password)
        self.assertIsNone(da.authenticate_user(email, f"!{password}!"))
        user = da.authenticate_user(email, password)
        self.assertEqual(user.email, email)

    def test_fetch_user_info(self):
        """
        Checks that `utils.data_access.fetch_user_info` return the correct
        information.
        """
        self.assertIsNone(da.fetch_user_info(NONEXISTENT_UUID))
        user = da.fetch_user_info(self.admin.uuid)
        self.assertEqual(user.email, self.admin.email)
        self.assertEqual(user.id, self.admin.id)

    def test_get_colors(self):
        """
        Checks that `utils.data_access.get_colors` return the correct
        information.
        """
        expected = {
            g.name: [{"id": c.id, "name": c.name, "comment": c.comment} for c in self.colors if c.genebank == g]
            for g in self.genebanks
        }

        colors = da.get_colors()
        self.assertDictEqual(colors, expected)

    def test_get_genebank(self):
        """
        Checks that `utils.data_access.get_genebank` return the correct
        information.

        The permission dependent behavior of this function is tested in the
        database functions, so in the interest of time it's not tested here.
        """
        self.assertIsNone(da.get_genebank(self.genebanks[0].id, NONEXISTENT_UUID))
        genebank = da.get_genebank(self.genebanks[0].id, self.admin.uuid)
        self.assertEqual(genebank["id"], self.genebanks[0].id)

    def test_get_genebanks(self):
        """
        Checks that `utils.data_access.get_genebanks` return the correct
        information.

        The permission dependent behavior of this function is tested in the
        database functions, so in the interest of time it's not tested here.
        """
        self.assertIsNone(da.get_genebanks(NONEXISTENT_UUID))
        genebanks = da.get_genebanks(self.admin.uuid)
        self.assertListEqual([g["id"] for g in genebanks], [g.id for g in self.genebanks])

    def test_get_herd(self):
        """
        Checks that `utils.data_access.get_herd` return the correct
        information.
        """
        self.assertIsNone(da.get_genebanks(NONEXISTENT_UUID))

        for user in [self.admin, self.manager, self.viewer, self.owner]:
            for herd in self.herds:
                value = da.get_herd(herd.herd, user.uuid)
                target = db.Herd.get(db.Herd.herd == herd.herd).filtered_dict(user)
                if target["genebank"] not in user.accessible_genebanks:
                    target = None
                else:
                    target["individuals"] = [i.as_dict() for i in herd_members(herd)]

                if value is None or target is None:
                    self.assertEqual(value, target)
                else:
                    # Sort individuals by number for consistent comparison
                    # (PostgreSQL may return in different order than SQLite)
                    if "individuals" in value and value["individuals"]:
                        value["individuals"] = sorted(value["individuals"], key=lambda x: x.get("number", ""))
                    if "individuals" in target and target["individuals"]:
                        target["individuals"] = sorted(target["individuals"], key=lambda x: x.get("number", ""))
                    self.assertDictEqual(value, target)

    def test_add_herd(self):
        """
        Checks that `utils.data_access.add_herd` works as intended.
        """
        forms = {
            "valid": {"genebank": self.genebanks[0].id, "herd": "N001"},
            "invalid": {"genebank": self.genebanks[0].id, "herd_name": "N002"},
        }

        invalid_user = da.add_herd(forms["valid"], NONEXISTENT_UUID)
        self.assertDictEqual(invalid_user, {"status": "error", "message": "Not logged in"})

        not_permitted = da.add_herd(forms["valid"], self.owner.uuid)
        self.assertDictEqual(not_permitted, {"status": "error", "message": "Forbidden"})

        missing_data = da.add_herd(forms["invalid"], self.admin.uuid)
        self.assertDictEqual(missing_data, {"status": "error", "message": "missing data"})

        valid = da.add_herd(forms["valid"], self.admin.uuid)
        self.assertDictEqual(valid, {"status": "success"})
        self.assertIsNotNone(db.Herd.get(db.Herd.herd == forms["valid"]["herd"]))

        exists = da.add_herd(forms["valid"], self.manager.uuid)
        self.assertDictEqual(exists, {"status": "error", "message": "herd ID already exists"})

    def test_update_herd(self):
        """
        Checks that `utils.data_access.update_herd` works as intended.
        """
        forms = {
            "valid": {"id": self.herds[0].id, "herd_name": "test"},
            "invalid": {"id": -1, "herd_name": "test"},  # Non-existent integer ID
        }

        invalid_user = da.update_herd(forms["valid"], NONEXISTENT_UUID)
        self.assertDictEqual(invalid_user, {"status": "error", "message": "Not logged in"})

        not_permitted = da.update_herd(forms["valid"], self.viewer.uuid)
        self.assertDictEqual(not_permitted, {"status": "error", "message": "Forbidden"})

        valid_owner = da.update_herd(forms["valid"], self.owner.uuid)
        self.assertDictEqual(valid_owner, {"status": "updated"})

        valid_manager = da.update_herd(forms["valid"], self.manager.uuid)
        self.assertDictEqual(valid_manager, {"status": "updated"})

        valid_admin = da.update_herd(forms["valid"], self.admin.uuid)
        self.assertDictEqual(valid_admin, {"status": "updated"})

        unknown = da.update_herd(forms["invalid"], self.admin.uuid)
        self.assertDictEqual(unknown, {"status": "error", "message": "Unknown herd"})

    def test_update_herd_rejects_unknown_privacy_values(self):
        """*_privacy takes None or public/authenticated/private; the legacy 200 error envelope otherwise."""
        herd_id = self.herds[0].id
        for user in (self.owner, self.manager, self.admin):
            for bad in ("hemlig", "", "PRIVATE", 5, True, ["private"], {"level": "private"}):
                result = da.update_herd({"id": herd_id, "email_privacy": bad, "herd_name": "Ny"}, user.uuid)
                self.assertDictEqual(result, {"status": "error", "message": "Invalid value for email_privacy"})
        stored = db.Herd.get_by_id(herd_id)
        self.assertEqual(stored.email_privacy, "authenticated")
        self.assertEqual(stored.herd_name, self.herds[0].herd_name)

        for good in ("public", "authenticated", "private", None):
            result = da.update_herd({"id": herd_id, "email_privacy": good}, self.owner.uuid)
            self.assertDictEqual(result, {"status": "updated"})
            self.assertEqual(db.Herd.get_by_id(herd_id).email_privacy, good)

        # authorization is checked first: a viewer learns nothing about the value
        forbidden = da.update_herd({"id": herd_id, "email_privacy": "hemlig"}, self.viewer.uuid)
        self.assertDictEqual(forbidden, {"status": "error", "message": "Forbidden"})

    def test_add_herd_ignores_non_column_keys(self):
        """Herd(**form) took _pk and genebank_id, so a manager could overwrite another genebank's herd."""
        other = self.herds[2]  # Mellerud's M3; self.manager manages Gotland only
        form = {"genebank": self.genebanks[0].id, "herd": "N001", "_pk": other.id, "genebank_id": self.genebanks[1].id}
        self.assertDictEqual(da.add_herd(form, self.manager.uuid), {"status": "success"})
        untouched = db.Herd.get_by_id(other.id)
        self.assertEqual((untouched.herd, untouched.genebank_id), ("M3", self.genebanks[1].id))
        created = db.Herd.get(db.Herd.herd == "N001")
        self.assertNotEqual(created.id, other.id)
        self.assertEqual(created.genebank_id, self.genebanks[0].id)

    def test_add_herd_membership_is_admin_only(self):
        ms = db.Membership.create(member_number=9, membership_status="active")
        gb = self.genebanks[0].id
        da.add_herd({"genebank": gb, "herd": "N001", "membership": ms.id}, self.manager.uuid)
        self.assertIsNone(db.Herd.get(db.Herd.herd == "N001").membership_id)
        da.add_herd({"genebank": gb, "herd": "N002", "membership": ms.id}, self.admin.uuid)
        self.assertEqual(db.Herd.get(db.Herd.herd == "N002").membership_id, ms.id)

    def test_update_herd_does_not_write_back_stale_ownership_columns(self):
        """The row is loaded before can_edit; a full-row save would undo a reassignment committed meanwhile."""
        g1 = self.herds[0]
        ms = db.Membership.create(member_number=9, membership_status="active")
        real_can_edit = db.User.can_edit

        def can_edit_then_reassign(user, identifier):
            allowed = real_can_edit(user, identifier)
            db.Herd.update(membership=ms).where(db.Herd.id == g1.id).execute()  # another request commits
            return allowed

        with mock.patch.object(db.User, "can_edit", can_edit_then_reassign):
            result = da.update_herd({"id": g1.id, "herd_name": "Ny"}, self.owner.uuid)
        self.assertDictEqual(result, {"status": "updated"})
        stored = db.Herd.get_by_id(g1.id)
        self.assertEqual((stored.herd_name, stored.membership_id), ("Ny", ms.id))

    def test_edit_herd_does_not_write_back_stale_ownership_columns(self):
        herd = db.Herd.get_by_id(self.herds[0].id)  # loaded before the reassignment below
        ms = db.Membership.create(member_number=9, membership_status="active")
        db.Herd.update(membership=ms).where(db.Herd.id == herd.id).execute()
        da.edit_herd(herd, {"name": "Ny"}, actor=self.admin)
        stored = db.Herd.get_by_id(herd.id)
        self.assertEqual((stored.name, stored.membership_id), ("Ny", ms.id))

    def test_add_herd_rejects_unknown_privacy_values(self):
        form = {"genebank": self.genebanks[0].id, "herd": "N001", "name_privacy": "hemlig"}
        result = da.add_herd(form, self.manager.uuid)
        self.assertDictEqual(result, {"status": "error", "message": "Invalid value for name_privacy"})
        self.assertFalse(db.Herd.select().where(db.Herd.herd == "N001").exists())

        form = {"genebank": self.genebanks[0].id, "herd": "N001", "name_privacy": "authenticated"}
        self.assertDictEqual(da.add_herd(form, self.manager.uuid), {"status": "success"})

    def test_get_individual(self):
        """
        Checks that `utils.data_access.get_individual` works as intended.
        """
        self.assertIsNone(da.get_individual(self.individuals[0].number, NONEXISTENT_UUID))
        self.assertIsNone(da.get_individual("does_not_exist", NONEXISTENT_UUID))
        for individual in self.individuals:
            value = da.get_individual(individual.number, self.admin.uuid)
            data = db.Individual.get(individual.id)
            expected = data.as_dict()
            self.assertDictEqual(value, expected)

    def test_form_to_individual(self):
        """
        Checks that `utils.data_access.form_to_individual` works as intended.
        """
        forms = {
            "invalid_number": {
                "number": self.individuals[0].number,
                "id": self.individuals[1].id,
            },
            "admin_update": {
                "number": self.individuals[0].number,
                "certificate": "new-cert",
                "birth_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "herd": self.herds[0].herd,
            },
            "unknown_color": {
                "number": "G1-9901",
                "color": "ultra-beige",
                "herd": self.herds[0].herd,
            },
            "unknown_origin": {
                "number": "G1-9901",
                "herd": self.herds[0].herd,
                "origin_herd": {"herd": "does-not-exist"},
            },
            "valid": {
                "number": self.individuals[0].number,
                "birth_date": datetime.now() - timedelta(days=30),
                "herd": self.herds[0].herd,
            },
        }
        self.assertRaises(ValueError, da.form_to_individual, forms["invalid_number"], self.admin)
        self.assertRaises(ValueError, da.form_to_individual, forms["unknown_color"], self.owner)
        self.assertRaises(ValueError, da.form_to_individual, forms["unknown_origin"], self.owner)

        updated = da.form_to_individual(forms["admin_update"], self.admin)
        self.assertEqual(updated, self.individuals[0])

    def test_add_individual(self):
        """
        Checks that `utils.data_access.add_individual` works as intended.
        """
        forms = {
            "unknown_herd": {"herd": "does-not-exist"},
            "valid": {
                "herd": self.herds[0].herd,
                "origin_herd": {"herd": self.herds[0].herd},
                "number": "G1-1922",
                "breeding": 1,
                "birth_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "selling_date": (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
            },
            "empty": {
                "herd": self.herds[1].herd,
                "origin_herd": {"herd": self.herds[1].herd},
                "number": None,
                "breeding": 2,
                "birth_date": (datetime(2021, 1, 1) + timedelta(days=30)).strftime("%Y-%m-%d"),
                "selling_date": None,
            },
            # Hack since sqlite do not have the extract date function
            "secondempty": {
                "herd": self.herds[1].herd,
                "origin_herd": {"herd": self.herds[1].herd},
                "number": "G2-2112",
                "breeding": 2,
                "birth_date": (datetime(2021, 1, 1) + timedelta(days=30)).strftime("%Y-%m-%d"),
                "selling_date": None,
            },
        }
        self.assertEqual(
            da.add_individual(forms["valid"], NONEXISTENT_UUID),
            {"status": "error", "message": "Not logged in"},
        )

        self.assertEqual(
            da.add_individual(forms["unknown_herd"], self.admin.uuid),
            {"status": "error", "message": "Individual must have a valid herd"},
        )

        self.assertEqual(
            da.add_individual(forms["valid"], self.viewer.uuid),
            {"status": "error", "message": "Forbidden"},
        )

        status = da.add_individual(forms["valid"], self.admin.uuid)
        self.assertEqual(
            status,
            {
                "status": "success",
                "number": forms["valid"]["number"],
                "message": "Individual Created",
            },
        )
        ind = da.get_individual(forms["valid"]["number"], self.admin.uuid)
        self.assertIsNotNone(ind)
        self.assertEqual(ind["herd"], {"id": 1, "herd": "G1", "herd_name": "Gotlandsherd1"})

        status = da.add_individual(forms["empty"], self.admin.uuid)
        self.assertEqual(
            status,
            {
                "status": "success",
                "message": "Individual Created",
                "number": "G2-2111",
            },
        )
        ind = da.get_individual(forms["empty"]["number"], self.admin.uuid)

        status = da.add_individual(forms["secondempty"], self.admin.uuid)
        self.assertEqual(
            status,
            {"status": "success", "message": "Individual Created", "number": "G2-2112"},
        )
        ind = da.get_individual(forms["secondempty"]["number"], self.admin.uuid)
        self.assertIsNotNone(ind)

        # Make sure you cannot add rabbits with already existing numbers
        status = da.add_individual(forms["valid"], self.admin.uuid)
        self.assertEqual(status, {"status": "error", "message": "Individual number already exists"})

    def test_update_individual(self):
        """
        Checks that `utils.data_access.update_individual` works as intended.
        """
        forms = {
            "unknown_herd": {"herd": "does-not-exist"},
            "valid": {
                "origin_herd": {
                    "herd": self.herds[0].herd,
                },
                "herd": self.herds[0].herd,
                "id": self.individuals[0].id,
                "number": self.individuals[0].number,
                "name": "new name",
                "birth_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
            },
        }
        self.assertEqual(
            da.add_individual(forms["valid"], NONEXISTENT_UUID),
            {"status": "error", "message": "Not logged in"},
        )

        self.assertEqual(
            da.add_individual(forms["valid"], self.viewer.uuid),
            {"status": "error", "message": "Forbidden"},
        )

        self.assertEqual(
            da.add_individual(forms["unknown_herd"], self.admin.uuid),
            {"status": "error", "message": "Individual must have a valid herd"},
        )

        self.individuals[0].name = "original name"

        status = da.update_individual(forms["valid"], self.admin.uuid)
        self.assertEqual(
            status,
            {
                "status": "success",
                "message": "Individual Updated",
                "digital_certificate": None,
            },
        )
        self.assertEqual(db.Individual.get(self.individuals[0].id).name, "new name")

        # Check herd update, we need update to be on a separate date
        forms["valid"]["herd"] = self.herds[1].herd
        forms["valid"]["origin_herd"] = {
            "herd": self.herds[0].herd,
        }
        forms["valid"]["selling_date"] = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

        status = da.update_individual(forms["valid"], self.admin.uuid)

        self.assertEqual(db.Individual.get(self.individuals[0].id).current_herd, self.herds[1])

        # TODO: also validate weights and bodyfat

    def test_get_individuals(self):
        """
        Checks that `utils.data_access.get_individuals` return the correct
        information.
        """
        self.assertIsNone(da.get_individuals(NONEXISTENT_UUID))

        def dateformat(date):
            """
            Returns dates in the chosen string format, or None.
            """
            return date.strftime("%Y-%m-%d") if date else None

        def parent(data):
            """
            Returns parent information or None.
            """
            if not data:
                return {"id": None, "name": None, "number": None}
            return {"id": data.id, "name": data.name, "number": data.number}

        # Add some herd tracking entries
        form = {
            "herd": self.individuals[0].current_herd.herd,
            "origin_herd": {"herd": self.individuals[0].current_herd.herd},
            "number": self.individuals[0].number,
            "id": self.individuals[0].id,
        }

        for n in range(0, 7):
            da.update_individual(form, self.admin.uuid)
            form["selling_date"] = (datetime.now() + timedelta(days=n * 365)).strftime("%Y-%m-%d")
            form["origin_herd"] = {"herd": self.individuals[0].current_herd.herd}

        # herds 0 and 1 are in genebank 0
        gb0_expected = []

        for ind in [
            self.parents[0],
            self.parents[1],  # no tracking rows: listed in its origin herd
            self.individuals[0],
            self.individuals[1],
            self.individuals[3],
        ]:
            active = (
                (
                    db.HerdTracking.select()
                    .where(db.HerdTracking.individual == ind)
                    .order_by(db.HerdTracking.herd_tracking_date.desc())[0]
                    .herd_tracking_date
                    > datetime.date(datetime.now() - timedelta(days=366))
                    if db.HerdTracking.select().where(db.HerdTracking.individual == ind).count()
                    else False
                )
                and (ind.current_herd.is_active or ind.current_herd.is_active is None)
                and ind.death_date is None
                and not ind.death_note
            )
            ind_info = {
                "id": ind.id,
                "name": ind.name,
                "certificate": ind.certificate,
                "digital_certificate": ind.digital_certificate,
                "number": ind.number,
                "sex": ind.sex,
                "birth_date": dateformat(ind.breeding.birth_date),
                "castration_date": None,
                "death_date": dateformat(ind.death_date),
                "death_note": ind.death_note,
                "litter_size": ind.breeding.litter_size,
                "notes": ind.notes,
                "color_note": ind.color_note,
                "father": parent(ind.breeding.father),
                "mother": parent(ind.breeding.mother),
                "color": {
                    "id": ind.color.id if ind.color else None,
                    "name": ind.color.name if ind.color else None,
                },
                "herd": {
                    "id": ind.current_herd.id,
                    "herd": ind.current_herd.herd,
                    "herd_name": ind.current_herd.herd_name,
                },
                "genebank": self.genebanks[0].name,
                "herd_active": ind.current_herd.is_active or ind.current_herd.is_active is None,
                "is_active": active,
                "alive": ind.death_date is None and not ind.death_note,
                "children": len(ind.children),
            }
            gb0_expected += [ind_info]

        gb0_value = da.get_individuals(self.genebanks[0].id, self.admin.uuid)
        # Sort both lists by id to ensure consistent comparison
        gb0_expected_sorted = sorted(gb0_expected, key=lambda x: x["id"])
        gb0_value_sorted = sorted(gb0_value, key=lambda x: x["id"])
        self.assertListEqual(gb0_expected_sorted, gb0_value_sorted)

    def test_get_all_individuals(self):
        """
        Checks that `utils.data_access.get_all_individuals` return the correct
        information.
        """
        value = da.get_all_individuals()
        expected = []
        for individual in self.individuals + self.parents:
            has_parents = (
                individual.breeding
                and individual.breeding.father is not None
                and individual.breeding.mother is not None
            )
            expected += [
                {
                    "id": str(individual.id),
                    "father": str(individual.breeding.father_id) if has_parents else "0",
                    "mother": str(individual.breeding.mother_id) if has_parents else "0",
                    "sex": "M" if individual.sex == "male" else "F",
                    "phenotype": str(individual.color.id) if individual.color else "0",
                }
            ]

        # sort both lists, as order isn't important
        self.assertListEqual(
            sorted(value, key=lambda x: x["id"]),
            sorted(expected, key=lambda x: x["id"]),
        )

    def test_get_breeding_events(self):
        """
        Checks that `utils.data_access.get_breeding_events` return the correct
        information.
        """
        self.assertEqual(da.get_breeding_events(self.herds[0].herd, NONEXISTENT_UUID), [])
        self.assertEqual(da.get_breeding_events("does_not_exist", self.admin.uuid), [])
        # lacking permissions
        self.assertEqual(da.get_breeding_events(self.herds[2].herd, self.viewer.uuid), [])

        breeding = db.Breeding.get(self.breeding[-1].id)
        expected = [breeding.as_dict()]

        # success
        self.assertEqual(da.get_breeding_events("G1", self.admin.uuid)[2], expected[0])

    def test_register_breeding(self):
        """
        Checks that `utils.data_access.register_breeding` works as intended.
        """
        valid_form = {
            "father": self.individuals[0].number,
            "mother": self.individuals[1].number,
            "breeding_herd": self.herds[0].herd,
            "date": datetime.today().strftime("%Y-%m-%d"),
        }
        invalid_mother = {
            "father": self.individuals[0].number,
            "mother": "invalid-mother",
            "breeding_herd": self.herds[0].herd,
            "date": datetime.today().strftime("%Y-%m-%d"),
        }
        invalid_father = {
            "father": "invalid-father",
            "breeding_herd": self.herds[0].herd,
            "mother": self.individuals[1].number,
            "date": datetime.today().strftime("%Y-%m-%d"),
        }
        missing_date = {
            "father": self.individuals[0].number,
            "mother": self.individuals[1].number,
            "breeding_herd": self.herds[0].herd,
            "herd": self.herds[0].herd,
        }
        invalid_date = {
            "father": self.individuals[0].number,
            "mother": self.individuals[1].number,
            "breeding_herd": self.herds[0].herd,
            "date": "20-31-11",
        }
        self.assertEqual(
            da.register_breeding(valid_form, NONEXISTENT_UUID),
            {"status": "error", "message": "Not logged in"},
        )
        self.assertEqual(
            da.register_breeding(invalid_mother, self.admin.uuid),
            {"status": "error", "message": "Unknown mother"},
        )
        self.assertEqual(
            da.register_breeding(invalid_father, self.admin.uuid),
            {"status": "error", "message": "Unknown father"},
        )
        self.assertEqual(
            da.register_breeding(missing_date, self.admin.uuid),
            {"status": "error", "message": "Date missing"},
        )
        self.assertEqual(
            da.register_breeding(invalid_date, self.admin.uuid),
            {
                "status": "error",
                "message": "Date must be formatted as yyyy-mm-dd or yyyy-mm-ddThh:mm:ss.sssZ.",
            },
        )
        result = da.register_breeding(valid_form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        self.assertIn("breeding_id", result)
        self.assertEqual(
            da.register_breeding(valid_form, self.admin.uuid),
            {"status": "error", "message": "Breeding already registered"},
        )

    def test_register_birth(self):
        """
        Checks that `utils.data_access.register_birth` works as intended.
        """
        valid_form = {
            "id": self.breeding[3].id,
            "date": datetime(2022, 2, 1).strftime("%Y-%m-%d"),
            "litter_size": 4,
        }
        invalid_id = {"id": -1}  # Non-existent integer ID
        missing_date = {"id": self.breeding[3].id, "litter_size": 4}
        invalid_date = {"id": self.breeding[3].id, "litter_size": 4, "date": "20-31-11"}
        missing_litter = {
            "id": self.breeding[3].id,
            "date": datetime.today().strftime("%Y-%m-%d"),
        }
        unknown_litter = {
            "id": self.breeding[3].id,
            "litter_size": "jamaica",
            "date": datetime.today().strftime("%Y-%m-%d"),
        }
        invalid_litter = {
            "id": self.breeding[3].id,
            "litter_size": 0,
            "date": datetime.today().strftime("%Y-%m-%d"),
        }
        self.assertEqual(
            da.register_birth(valid_form, NONEXISTENT_UUID),
            {"status": "error", "message": "Not logged in"},
        )
        self.assertEqual(
            da.register_birth(invalid_id, self.admin.uuid),
            {"status": "error", "message": "Breeding does not exist"},
        )
        self.assertEqual(
            da.register_birth(missing_date, self.admin.uuid),
            {"status": "error", "message": "Date missing"},
        )
        self.assertEqual(
            da.register_birth(invalid_date, self.admin.uuid),
            {
                "status": "error",
                "message": "Date must be formatted as yyyy-mm-dd or yyyy-mm-ddThh:mm:ss.sssZ.",
            },
        )
        self.assertEqual(
            da.register_birth(missing_litter, self.admin.uuid),
            {"status": "error", "message": "Missing litter size."},
        )
        self.assertEqual(
            da.register_birth(unknown_litter, self.admin.uuid),
            {"status": "error", "message": "Unknown litter size."},
        )
        self.assertEqual(
            da.register_birth(invalid_litter, self.admin.uuid),
            {"status": "error", "message": "Litter size must be larger than zero."},
        )
        # register_birth now also assigns and surfaces the stored litter_number.
        self.assertEqual(
            da.register_birth(valid_form, self.admin.uuid),
            {"status": "success", "litter_number": 1},
        )
        self.assertEqual(
            da.register_birth(valid_form, self.admin.uuid),
            {"status": "error", "message": "Birth already registered."},
        )

    def test_update_breeding(self):
        """
        Checks that `utils.data_access.update_breeding` works as intended.
        """
        # Swap mother/father — both born well before breeding[0].birth_date (2021-02-01)
        valid_form = {
            "id": self.breeding[0].id,
            "father": self.parents[0].number,  # born 2019-02-01
            "mother": self.parents[1].number,  # born 2017-02-01
        }
        invalid_id = {"id": -1}  # Non-existent integer ID
        invalid_mother = {
            "id": self.breeding[0].id,
            "father": self.individuals[0].number,
            "mother": "invalid-mother",
        }
        invalid_father = {
            "id": self.breeding[0].id,
            "father": "invalid-father",
            "mother": self.individuals[1].number,
        }
        invalid_date = {
            "id": self.breeding[0].id,
            "father": self.individuals[0].number,
            "mother": self.individuals[1].number,
            "breed_date": "20-31-11",
        }
        unknown_litter = {"id": self.breeding[0].id, "litter_size": "jamaica"}
        invalid_litter = {"id": self.breeding[0].id, "litter_size": 0}
        self.assertEqual(
            da.update_breeding(valid_form, NONEXISTENT_UUID),
            {"status": "error", "message": "Not logged in"},
        )
        self.assertEqual(
            da.update_breeding(invalid_id, self.admin.uuid),
            {"status": "error", "message": "Breeding does not exist"},
        )

        self.assertEqual(
            da.update_breeding(invalid_mother, self.admin.uuid),
            {"status": "error", "message": "Unknown mother"},
        )
        self.assertEqual(
            da.update_breeding(invalid_father, self.admin.uuid),
            {"status": "error", "message": "Unknown father"},
        )
        self.assertEqual(
            da.update_breeding(invalid_date, self.admin.uuid),
            {
                "status": "error",
                "message": "Date must be formatted as yyyy-mm-dd or yyyy-mm-ddThh:mm:ss.sssZ.",
            },
        )
        self.assertEqual(
            da.update_breeding(unknown_litter, self.admin.uuid),
            {"status": "error", "message": "Unknown litter size."},
        )
        self.assertEqual(
            da.update_breeding(invalid_litter, self.admin.uuid),
            {"status": "error", "message": "Litter size must be larger than zero."},
        )
        self.assertEqual(da.update_breeding(valid_form, self.admin.uuid), {"status": "success"})

    # --- Breeding date validation tests ---

    def test_register_breeding_future_date(self):
        """Breed date in the future should be rejected."""
        future = (datetime.today() + timedelta(days=10)).strftime("%Y-%m-%d")
        form = {
            "father": self.parents[1].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": future,
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("framtiden", result["message"])

    def test_register_breeding_before_parent_birth(self):
        """Breed date before parent's birth date should be rejected."""
        # parents[0] born 2019-02-01
        form = {
            "father": self.parents[1].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2018-01-01",  # before parents[0]'s birth
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("moderns födelsedatum", result["message"])

    def test_register_birth_future_date(self):
        """Birth date in the future should be rejected."""
        future = (datetime.today() + timedelta(days=10)).strftime("%Y-%m-%d")
        form = {
            "id": self.breeding[3].id,
            "date": future,
            "litter_size": 4,
        }
        result = da.register_birth(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("framtiden", result["message"])

    def test_register_birth_before_parent_birth(self):
        """Birth date before parent's birth date should be rejected."""
        # breeding[3] mother=parents[2] born 2019-02-01
        form = {
            "id": self.breeding[3].id,
            "date": "2017-01-01",
            "litter_size": 4,
        }
        result = da.register_birth(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("moderns födelsedatum", result["message"])

    def test_register_birth_parent_too_young(self):
        """Parent must be at least MIN_PARENT_AGE_DAYS old at birth."""
        # breeding[3] mother=parents[2] born 2019-02-01
        # 100 days after mother's birth → too young
        form = {
            "id": self.breeding[3].id,
            "date": "2019-05-12",
            "litter_size": 4,
        }
        result = da.register_birth(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("180 dagar", result["message"])

    def test_register_birth_gestation_too_short(self):
        """Gestation shorter than MIN_GESTATION_DAYS should be rejected."""
        # breeding[3] breed_date=2022-01-01
        form = {
            "id": self.breeding[3].id,
            "date": "2022-01-10",  # 9 days gestation
            "litter_size": 4,
        }
        result = da.register_birth(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("Dräktighetsperioden", result["message"])

    def test_register_birth_gestation_too_long(self):
        """Gestation longer than MAX_GESTATION_DAYS should be rejected."""
        # breeding[3] breed_date=2022-01-01
        form = {
            "id": self.breeding[3].id,
            "date": "2022-03-01",  # 59 days gestation
            "litter_size": 4,
        }
        result = da.register_birth(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("Dräktighetsperioden", result["message"])

    def test_update_breeding_parent_too_young(self):
        """Changing parent to one too young for the birth date should be rejected for an owner.

        Admins and genebank managers get the same finding as a warning instead — see
        test_update_breeding_admin_date_error_becomes_warning
        """
        # The guard for certified kits is covered in test_breeding_v2_api; this test is about the validation.
        db.Individual.update(certificate=None, digital_certificate=None).where(
            db.Individual.breeding == self.breeding[0]
        ).execute()
        # breeding[0]: birth_date=2021-02-01
        # individuals[0] born 2021-02-01 → 0 days old at birth → too young
        form = {
            "id": self.breeding[0].id,
            "mother": self.individuals[0].number,
        }
        result = da.update_breeding(form, self.owner.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("180 dagar", result["message"])

    def test_update_breeding_future_breed_date(self):
        """Updating breed_date to future should be rejected for an owner."""
        future = (datetime.today() + timedelta(days=10)).strftime("%Y-%m-%d")
        form = {
            "id": self.breeding[0].id,
            "breed_date": future,
        }
        result = da.update_breeding(form, self.owner.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("framtiden", result["message"])

    def test_update_breeding_admin_date_error_becomes_warning(self):
        """An admin may correct a historical row that today's rules refuse —
        the date findings come back as warnings instead of blocking the save."""
        future = (datetime.today() + timedelta(days=10)).strftime("%Y-%m-%d")
        form = {
            "id": self.breeding[0].id,
            "breed_date": future,
        }
        result = da.update_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        self.assertTrue(any("framtiden" in w for w in result["warnings"]))

    def test_update_breeding_admin_cannot_downgrade_same_individual_as_both_parents(self):
        """Fix round 1, item 1: the downgrade covers DATE findings only. Setting father to
        the mother's number blocks for an admin too, and the stored parents are unchanged."""
        form = {
            "id": self.breeding[0].id,
            "mother": self.parents[0].number,
            "father": self.parents[0].number,
        }
        result = da.update_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("Samma individ", result["message"])
        reloaded = db.Breeding.get(db.Breeding.id == self.breeding[0].id)
        self.assertEqual(reloaded.mother_id, self.parents[0].id)
        self.assertEqual(reloaded.father_id, self.parents[1].id)

    def test_update_breeding_manager_cannot_downgrade_wrong_sex_parent(self):
        """Fix round 1, item 1: a wrong-sex parent blocks for a manager of the litter's own
        genebank — the role that DOES get the date downgrade."""
        # parents[2] is male, so using him as mother is a role error.
        self.parents[2].sex = "male"
        self.parents[2].save()
        form = {
            "id": self.breeding[0].id,
            "mother": self.parents[2].number,
        }
        result = da.update_breeding(form, self.manager.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("Fel kön", result["message"])
        reloaded = db.Breeding.get(db.Breeding.id == self.breeding[0].id)
        self.assertEqual(reloaded.mother_id, self.parents[0].id)

    def test_update_breeding_manager_of_litter_genebank_gets_warning(self):
        """The downgrade applies to a manager of the litter's
        own genebank, not to a manager of any genebank."""
        future = (datetime.today() + timedelta(days=10)).strftime("%Y-%m-%d")
        form = {"id": self.breeding[0].id, "breed_date": future}
        # self.manager manages genebanks[0], which owns herds[0] = breeding[0]'s herd.
        result = da.update_breeding(form, self.manager.uuid)
        self.assertEqual(result["status"], "success")
        self.assertTrue(any("framtiden" in w for w in result["warnings"]))

    def test_update_breeding_manager_of_other_genebank_still_blocked(self):
        """A manager of a different genebank is treated like an owner: the finding blocks."""
        other_manager = da.register_user("other-man", "pass")
        other_manager.add_role("manager", self.genebanks[1].id)
        future = (datetime.today() + timedelta(days=10)).strftime("%Y-%m-%d")
        form = {"id": self.breeding[0].id, "breed_date": future}
        result = da.update_breeding(form, other_manager.uuid)
        # can_edit() already refuses a manager of another genebank ("Forbidden"),
        # so the downgrade branch is unreachable for them; either way the row
        # must be untouched.
        self.assertEqual(result["status"], "error")
        reloaded = db.Breeding.get(db.Breeding.id == self.breeding[0].id)
        self.assertEqual(str(reloaded.breed_date)[:10], str(self.breeding[0].breed_date)[:10])

    def test_update_breeding_unchanged_echo_skips_validation(self):
        """Legacy PATCHes the whole object, so a row whose stored state no
        longer satisfies today's rules must still accept a notes-only edit."""
        invalid_row = db.Breeding.create(
            breed_date=datetime(2021, 1, 1),
            # 151 days gestation — far outside MIN/MAX, as 53 real litters are
            birth_date=datetime(2021, 6, 1),
            mother=self.parents[0],
            father=self.parents[1],
            litter_size=2,
            litter_size6w=2,
            breeding_herd_id=self.herds[0],
        )
        form = {
            "id": invalid_row.id,
            "mother": self.parents[0].number,
            "father": self.parents[1].number,
            "breed_date": "2021-01-01",
            "birth_date": "2021-06-01",
            "litter_size": 2,
            "litter_size6w": 2,
            "breed_notes": "Anteckning från legacy",
        }
        result = da.update_breeding(form, self.owner.uuid)
        self.assertEqual(result, {"status": "success"})

    # --- Story 2.6: Breeding validation hardening ---

    def test_overlapping_birth_blocked(self):
        """Birth within 35 days of existing birth for same mother should be rejected."""
        # parents[0] has birth on 2021-02-01 (breeding[0])
        # Register a new breeding, then try birth within 35 days
        form = {
            "father": self.parents[1].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2021-02-02",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        breeding_id = result["breeding_id"]

        # Birth on 2021-03-02: 29 days after existing birth 2021-02-01 → blocked
        birth_form = {
            "id": breeding_id,
            "date": "2021-03-02",
            "litter_size": 4,
        }
        result = da.register_birth(birth_form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("35 dagar", result["message"])

    def test_mating_during_gestation_blocked(self):
        """Mating during an existing gestation period should be rejected."""
        # parents[2] has breeding[3]: breed_date=2022-01-01, no birth_date
        # New mating on 2022-01-20 falls within gestation window → blocked
        form = {
            "father": self.parents[3].number,
            "mother": self.parents[2].number,
            "breeding_herd": self.herds[2].herd,
            "date": "2022-01-20",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("dräktig", result["message"])

    def test_same_individual_as_both_parents_blocked(self):
        """Same individual as both mother and father should be rejected."""
        form = {
            "father": self.parents[0].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2023-06-01",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("Samma individ", result["message"])

    def test_wrong_sex_for_parent_role_blocked(self):
        """Male as mother or female as father should be rejected."""
        # Set parents[0] as male (wrong for mother role)
        self.parents[0].sex = "male"
        self.parents[0].save()
        self.parents[1].sex = "male"
        self.parents[1].save()

        form = {
            "father": self.parents[1].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2023-06-01",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("Fel kön", result["message"])

    def test_wrong_sex_female_as_father_blocked(self):
        """Female as father should be rejected."""
        self.parents[0].sex = "female"
        self.parents[0].save()
        self.parents[1].sex = "female"  # Wrong for father role
        self.parents[1].save()

        form = {
            "father": self.parents[1].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2023-06-01",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("Fel kön", result["message"])

    def test_correct_sex_allowed(self):
        """Correctly sexed parents should pass sex validation."""
        self.parents[0].sex = "female"
        self.parents[0].save()
        self.parents[1].sex = "male"
        self.parents[1].save()

        form = {
            "father": self.parents[1].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2023-06-01",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "success")

    def test_warnings_returned_but_dont_block(self):
        """Warnings should be returned with success, not blocking registration."""
        # Register breeding far enough from existing births
        form = {
            "father": self.parents[1].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2024-10-01",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        breeding_id = result["breeding_id"]

        # Birth on 2024-10-30: parents are >5 years old → warning
        # parents[0] born 2019-02-01, parents[1] born 2017-02-01
        birth_form = {
            "id": breeding_id,
            "date": "2024-10-30",
            "litter_size": 4,
        }
        result = da.register_birth(birth_form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        self.assertIn("warnings", result)
        warning_text = " ".join(result["warnings"])
        self.assertIn("5 år", warning_text)

    def test_large_litter_warning(self):
        """Litter size > 12 should produce a warning."""
        form = {
            "father": self.parents[1].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2024-10-01",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        breeding_id = result["breeding_id"]

        birth_form = {
            "id": breeding_id,
            "date": "2024-10-30",
            "litter_size": 15,
        }
        result = da.register_birth(birth_form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        self.assertIn("warnings", result)
        warning_text = " ".join(result["warnings"])
        self.assertIn("12 ungar", warning_text)

    def test_close_inbreeding_warning(self):
        """Mating parent-child should produce an inbreeding warning."""
        # individuals[0] was born from breeding[0] (mother=parents[0], father=parents[1])
        # Mating individuals[0] as mother with parents[1] (her father) = inbreeding
        form = {
            "father": self.parents[1].number,
            "mother": self.individuals[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2024-01-15",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        self.assertIn("warnings", result)
        warning_text = " ".join(result["warnings"])
        self.assertIn("inavelsparning", warning_text)

    def test_half_sibling_warning(self):
        """Half siblings (sharing one parent) should produce inbreeding warning."""
        # Create a half-sibling of individuals[0]: same mother (parents[0]), different father (parents[3])
        half_sib_breeding = db.Breeding.create(
            breed_date=datetime(2021, 6, 1),
            birth_date=datetime(2021, 7, 1),
            mother=self.parents[0],
            father=self.parents[3],
            litter_size=2,
            breeding_herd_id=self.herds[0],
        )
        half_sib = db.Individual.create(
            origin_herd=self.herds[0],
            breeding=half_sib_breeding,
            number="G1-2133",
        )
        # Mate individuals[0] (mother) with half_sib (father) → half siblings
        form = {
            "father": half_sib.number,
            "mother": self.individuals[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2024-01-15",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        self.assertIn("warnings", result)
        warning_text = " ".join(result["warnings"])
        self.assertIn("inavelsparning", warning_text)

    def test_many_litters_per_year_warning(self):
        """More than 4 litters per year for same mother should produce a warning."""
        # Create 4 births in 2023 for parents[0], well-spaced to avoid overlap checks
        for month in [3, 5, 7, 9]:
            db.Breeding.create(
                breed_date=datetime(2023, month - 1, 1),
                birth_date=datetime(2023, month, 1),
                mother=self.parents[0],
                father=self.parents[1],
                litter_size=3,
                breeding_herd_id=self.herds[0],
            )
        # Register a 5th breeding + birth in 2023
        form = {
            "father": self.parents[1].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2023-10-15",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        breeding_id = result["breeding_id"]

        birth_form = {
            "id": breeding_id,
            "date": "2023-11-15",
            "litter_size": 4,
        }
        result = da.register_birth(birth_form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        self.assertIn("warnings", result)
        warning_text = " ".join(result["warnings"])
        self.assertIn("4 eller fler kullar", warning_text)

    def test_same_day_birth_blocked(self):
        """Birth on the exact same date as existing birth for same mother should be rejected."""
        # parents[0] has birth on 2021-02-01 (breeding[0])
        # Use breed_date before existing gestation to avoid mating-during-gestation error
        form = {
            "father": self.parents[1].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2020-12-31",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        breeding_id = result["breeding_id"]

        # Birth on 2021-02-01: same date as existing birth → blocked (days_diff == 0)
        birth_form = {
            "id": breeding_id,
            "date": "2021-02-01",
            "litter_size": 4,
        }
        result = da.register_birth(birth_form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("35 dagar", result["message"])

    def test_mating_same_date_as_existing_blocked(self):
        """Mating on the exact same date as an existing mating should be rejected."""
        # parents[2] has breeding[3]: breed_date=2022-01-01, no birth_date
        # New mating on same date with different father → blocked
        form = {
            "father": self.parents[1].number,
            "mother": self.parents[2].number,
            "breeding_herd": self.herds[2].herd,
            "date": "2022-01-01",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("dräktig", result["message"])

    def test_full_siblings_different_litters_warning(self):
        """Full siblings from different litters should produce inbreeding warning."""
        # individuals[0] from breeding[0] (mother=parents[0], father=parents[1])
        # individuals[1] from breeding[2] (mother=parents[0], father=parents[1])
        # Same parents, different litters → full siblings
        form = {
            "father": self.individuals[1].number,
            "mother": self.individuals[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2024-01-15",
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "success")
        self.assertIn("warnings", result)
        warning_text = " ".join(result["warnings"])
        self.assertIn("inavelsparning", warning_text)

    def test_existing_validations_still_work(self):
        """Regression: existing date validations should be unchanged."""
        # Future breed date → error
        future = (datetime.today() + timedelta(days=10)).strftime("%Y-%m-%d")
        form = {
            "father": self.parents[1].number,
            "mother": self.parents[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": future,
        }
        result = da.register_breeding(form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("framtiden", result["message"])

        # Gestation too short → error
        birth_form = {
            "id": self.breeding[3].id,
            "date": "2022-01-10",
            "litter_size": 4,
        }
        result = da.register_birth(birth_form, self.admin.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("Dräktighetsperioden", result["message"])

    # ── Story 2.7: Ownership validation for breeding ──

    def test_was_in_herd_at_date_current_herd(self):
        """Individual currently in herd → True at today's date."""
        # individuals[0] is in herds[0] (G1) since 2021-02-01
        result = da.was_in_herd_at_date(self.individuals[0].id, self.herds[0].id, datetime(2021, 6, 1).date())
        self.assertTrue(result)

    def test_was_in_herd_at_date_past_herd(self):
        """Individual WAS in herd at a past date but has since been transferred → True for past date."""
        # individuals[2] was in herds[0] (G1) at 2021-02-01, then transferred to herds[2] (M3) ~30 days ago
        result = da.was_in_herd_at_date(self.individuals[2].id, self.herds[0].id, datetime(2021, 6, 1).date())
        self.assertTrue(result)

    def test_was_in_herd_at_date_wrong_herd(self):
        """Individual was NEVER in the given herd → False."""
        # individuals[0] is in herds[0] (G1), never in herds[1] (G2)
        result = da.was_in_herd_at_date(self.individuals[0].id, self.herds[1].id, datetime(2021, 6, 1).date())
        self.assertFalse(result)

    def test_was_in_herd_at_date_before_tracking(self):
        """Date is before any tracking entry → False."""
        # individuals[0] first tracking is 2021-02-01
        result = da.was_in_herd_at_date(self.individuals[0].id, self.herds[0].id, datetime(2020, 1, 1).date())
        self.assertFalse(result)

    def test_was_in_herd_at_date_after_transfer(self):
        """Individual transferred away — checking at date after transfer for OLD herd → False."""
        # individuals[2] transferred from herds[0] to herds[2] ~30 days ago
        today = datetime.now().date()
        result = da.was_in_herd_at_date(self.individuals[2].id, self.herds[0].id, today)
        self.assertFalse(result)

    def test_was_in_herd_at_date_after_transfer_new_herd(self):
        """Individual transferred — checking at date after transfer for NEW herd → True."""
        today = datetime.now().date()
        result = da.was_in_herd_at_date(self.individuals[2].id, self.herds[2].id, today)
        self.assertTrue(result)

    def test_breeding_ownership_owner_current_herd(self):
        """Owner registers mating for doe currently in their herd → allowed."""
        form = {
            "father": self.parents[1].number,
            "mother": self.individuals[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2023-06-01",
        }
        result = da.register_breeding(form, self.owner.uuid)
        self.assertEqual(result["status"], "success")

    def test_breeding_ownership_owner_past_herd(self):
        """Owner registers mating for doe that WAS in their herd at breed_date but since sold → allowed."""
        # individuals[2] was in herds[0] (owner's herd) at 2021-06-01
        form = {
            "father": self.parents[1].number,
            "mother": self.individuals[2].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2021-06-01",
        }
        result = da.register_breeding(form, self.owner.uuid)
        self.assertEqual(result["status"], "success")

    def test_breeding_ownership_never_in_herd(self):
        """Owner registers mating for doe that was NEVER in their herd → blocked."""
        # individuals[1] is in herds[1] (G2), owner owns herds[0] (G1)
        form = {
            "father": self.parents[1].number,
            "mother": self.individuals[1].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2023-06-01",
        }
        result = da.register_breeding(form, self.owner.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("tillhörde inte din besättning", result["message"])

    def test_breeding_ownership_bought_pregnant(self):
        """Owner registers mating for a doe bought pregnant — the mating predates the transfer
        but she is in the herd now → allowed.

        Only a doe the user has never owned is refused; see
        test_breeding_ownership_never_in_herd.
        """
        # Create an individual born early in a different herd, then transferred to owner's herd later
        early_breeding = db.Breeding.create(
            breed_date=datetime(2018, 6, 1),
            birth_date=datetime(2018, 7, 15),
            litter_size=3,
            litter_size6w=3,
            breeding_herd_id=self.herds[1],
        )
        doe = db.Individual.create(
            origin_herd=self.herds[1],
            breeding=early_breeding,
            number="G2-1811",
        )
        # Born in herds[1] at 2018-07-15
        ht_row("BIRTH", herd=self.herds[1], individual=doe, herd_tracking_date=datetime(2018, 7, 15))
        # Transferred to owner's herd (herds[0]) on 2022-01-01
        ht_row(
            "TRANSFER",
            from_herd=self.herds[1],
            herd=self.herds[0],
            individual=doe,
            herd_tracking_date=datetime(2022, 1, 1),
        )
        # Register the breeding at a date BEFORE the transfer (2021-06-01) — she was in
        # herds[1] then, but she is in the owner's herd now
        form = {
            "father": self.parents[1].number,
            "mother": doe.number,
            "breeding_herd": self.herds[0].herd,
            "date": "2021-06-01",
        }
        result = da.register_breeding(form, self.owner.uuid)
        self.assertEqual(result["status"], "success")

    def test_birth_ownership_doe_bought_pregnant(self):
        """Owner registers the birth for a doe bought pregnant — the birth predates the
        transfer but she is in the herd now → allowed."""
        early_breeding = db.Breeding.create(
            breed_date=datetime(2018, 6, 1),
            birth_date=datetime(2018, 7, 15),
            litter_size=3,
            litter_size6w=3,
            breeding_herd_id=self.herds[1],
        )
        doe = db.Individual.create(
            origin_herd=self.herds[1],
            breeding=early_breeding,
            number="G2-1812",
        )
        ht_row("BIRTH", herd=self.herds[1], individual=doe, herd_tracking_date=datetime(2018, 7, 15))
        # Bought into the owner's herd well after the litter below was born
        ht_row(
            "TRANSFER",
            from_herd=self.herds[1],
            herd=self.herds[0],
            individual=doe,
            herd_tracking_date=datetime(2022, 1, 1),
        )
        breeding = db.Breeding.create(
            breed_date=datetime(2021, 6, 1),
            mother=doe,
            father=self.parents[1],
            breeding_herd_id=self.herds[0],
        )
        form = {"id": breeding.id, "date": "2021-07-01", "litter_size": 3}
        result = da.register_birth(form, self.owner.uuid)
        self.assertEqual(result["status"], "success")

    def test_birth_ownership_null_mother_is_refused_not_crash(self):
        """A null-mother "utan kull" litter belongs to no herd — refused, never an
        AttributeError."""
        breeding = db.Breeding.create(
            breed_date=datetime(2021, 6, 1),
            breeding_herd_id=self.herds[0],
        )
        form = {"id": breeding.id, "date": "2021-07-01", "litter_size": 3}
        result = da.register_birth(form, self.owner.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("tillhörde inte din besättning", result["message"])

    def test_birth_ownership_never_in_herd(self):
        """Owner registers the birth for a doe that was never in their herd → blocked."""
        breeding = db.Breeding.create(
            breed_date=datetime(2021, 6, 1),
            mother=self.individuals[1],  # G2-2011, always in herds[1]
            father=self.parents[1],
            breeding_herd_id=self.herds[0],
        )
        form = {"id": breeding.id, "date": "2021-07-01", "litter_size": 3}
        result = da.register_birth(form, self.owner.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("tillhörde inte din besättning", result["message"])

    def test_breeding_ownership_manager_bypass(self):
        """Manager registers for any herd in genebank → allowed (bypass)."""
        form = {
            "father": self.parents[1].number,
            "mother": self.individuals[0].number,
            "breeding_herd": self.herds[0].herd,
            "date": "2023-07-01",
        }
        result = da.register_breeding(form, self.manager.uuid)
        self.assertEqual(result["status"], "success")

    def test_breeding_ownership_manager_of_other_genebank_is_checked(self):
        """A Mellerud manager who owns G1 gets the owner check on a G1 litter — the
        manager bypass covers only the breeding herd's own genebank."""
        doe = db.Individual.create(origin_herd=self.herds[1], number="G2-2001", sex="female")  # never in G1
        ht_row("BIRTH", herd=self.herds[1], individual=doe, herd_tracking_date=datetime(2020, 1, 1))
        form = {"mother": doe.number, "father": self.parents[1].number, "date": "2022-06-01", "breeding_herd": "G1"}
        # control: the plain G1 owner is refused
        control = da.register_breeding(form, self.owner.uuid)
        self.assertIn("tillhörde inte din besättning", control.get("message", ""), control)

        self.manager.privileges = [
            {"level": "manager", "genebank": self.genebanks[1].id},
            {"level": "owner", "herd": self.herds[0].id},
        ]
        self.manager.save()
        result = da.register_breeding(form, self.manager.uuid)
        self.assertEqual(result["status"], "error", result)
        self.assertIn("tillhörde inte din besättning", result["message"])
        self.assertFalse(db.Breeding.select().where(db.Breeding.mother == doe).exists())

    def test_birth_ownership_manager_of_other_genebank_is_checked(self):
        """A Gotland manager who owns G1 gets the owner check on a Mellerud litter."""
        mellerud_litter = self.breeding[3]  # herd M3, unborn, doe never in G1
        form = {"id": mellerud_litter.id, "date": "2022-02-01", "litter_size": 3}
        # control: the plain G1 owner is refused
        control = da.register_birth(form, self.owner.uuid)
        self.assertIn("tillhörde inte din besättning", control.get("message", ""), control)

        self.manager.add_role("owner", self.herds[0].id)  # manager of Gotland only
        result = da.register_birth(form, self.manager.uuid)
        fresh = db.Breeding.get_by_id(mellerud_litter.id)
        self.assertEqual(result["status"], "error", f"{result}; birth_date={fresh.birth_date}")
        self.assertIn("tillhörde inte din besättning", result["message"])
        self.assertIsNone(fresh.birth_date)
        self.assertFalse(db.Bunny.select().where(db.Bunny.breeding == mellerud_litter.id).exists())

    def test_birth_ownership_doe_sold_during_pregnancy(self):
        """Doe sold during pregnancy — original owner registers birth at date she was still theirs → allowed."""
        # Create an older doe born in 2019, initially in owner's herd, then sold
        old_breeding = db.Breeding.create(
            breed_date=datetime(2018, 6, 1),
            birth_date=datetime(2018, 7, 15),
            litter_size=2,
            litter_size6w=2,
            breeding_herd_id=self.herds[0],
        )
        doe = db.Individual.create(
            origin_herd=self.herds[0],
            breeding=old_breeding,
            number="G1-1812",
        )
        ht_row("BIRTH", herd=self.herds[0], individual=doe, herd_tracking_date=datetime(2018, 7, 15))
        # Sold to herds[1] on 2023-01-01
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            individual=doe,
            herd_tracking_date=datetime(2023, 1, 1),
        )
        # Breeding happened while she was still in owner's herd
        breeding = db.Breeding.create(
            breed_date=datetime(2022, 10, 1),
            mother=doe,
            father=self.parents[1],
            breeding_herd_id=self.herds[0],
        )
        # Birth date 2022-11-01 — she was still in herds[0] then (sold 2023-01-01)
        form = {
            "id": breeding.id,
            "date": "2022-11-01",
            "litter_size": 3,
        }
        result = da.register_birth(form, self.owner.uuid)
        self.assertEqual(result["status"], "success")


class TestGetPaginatedIndividualsVoided(DatabaseTest):
    """Voided Individuals must be absent from get_paginated_individuals."""

    def setUp(self):
        super().setUp()

    def test_voided_individual_excluded_from_paginated_list(self):
        """A voided Individual is not returned; a non-voided sibling is."""
        herd = self.herds[0]
        breeding = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=datetime(2030, 3, 1),
            litter_size=2,
            litter_number=1,
        )
        visible = db.Individual.create(
            number="G1-3001",
            origin_herd=herd,
            breeding=breeding,
            sex="female",
            voided=False,
        )
        voided_ind = db.Individual.create(
            number="G1-3002",
            origin_herd=herd,
            breeding=breeding,
            sex="male",
            voided=True,
        )
        ht_row("BIRTH", herd=herd, individual=visible, herd_tracking_date=datetime.now())
        ht_row("BIRTH", herd=herd, individual=voided_ind, herd_tracking_date=datetime.now())

        result = da.get_paginated_individuals(self.admin.uuid)
        numbers = [i["number"] for i in result["items"]]
        self.assertIn(visible.number, numbers, "Non-voided individual should appear in listing")
        self.assertNotIn(voided_ind.number, numbers, "Voided individual must NOT appear in listing")


class TestBreedingOffspringExcludesVoided(DatabaseTest):
    """Voided Individuals must be absent from the breeding offspring list."""

    def test_voided_individual_excluded_from_breeding_offspring(self):
        """A voided sibling must not appear in get_breeding_events_with_ind; non-voided must."""
        herd = self.herds[0]
        breeding = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=datetime(2030, 3, 1),
            litter_size=2,
            litter_number=1,
        )
        visible = db.Individual.create(
            number="G1-3011",
            origin_herd=herd,
            breeding=breeding,
            sex="female",
            voided=False,
        )
        voided_ind = db.Individual.create(
            number="G1-3012",
            origin_herd=herd,
            breeding=breeding,
            sex="male",
            voided=True,
        )
        ht_row("BIRTH", herd=herd, individual=visible, herd_tracking_date=datetime.now())
        ht_row("BIRTH", herd=herd, individual=voided_ind, herd_tracking_date=datetime.now())

        events = da.get_breeding_events_with_ind(herd.herd, self.admin.uuid)
        matching = [e for e in events if e.get("id") == breeding.id]
        self.assertEqual(len(matching), 1, "Breeding must appear in events list")
        ind_numbers = [i.get("number") for i in matching[0]["individuals"]]
        self.assertIn(visible.number, ind_numbers, "Non-voided individual should appear in breeding offspring")
        self.assertNotIn(voided_ind.number, ind_numbers, "Voided individual must NOT appear in breeding offspring")


class TestCertificateRenameS3(DatabaseTest):
    """The PDF is staged at ~<new> inside the transaction; it moves into place after commit."""

    def setUp(self):
        super().setUp()
        self.ind = self.individuals[0]
        db.Individual.update(digital_certificate=100001, certificate=None).where(
            db.Individual.id == self.ind.id
        ).execute()
        self.client = mock.Mock()
        self.calls = []
        self.client.copy_object.side_effect = lambda **kw: self.calls.append(
            ("copy", kw["old_object_name"], kw["object_name"], db.DATABASE.transaction_depth() > 0)
        )
        self.client.delete_object.side_effect = lambda key: self.calls.append(
            ("delete", key, db.DATABASE.transaction_depth() > 0)
        )

    def _rename(self, **extra):
        form = {"id": self.ind.id, "number": "G1-2119", "herd": "G1", **extra}
        with mock.patch("utils.s3.get_s3_client", return_value=self.client):
            return da.update_individual(form, self.manager.uuid)

    def _number(self):
        return db.Individual.get_by_id(self.ind.id).number

    def test_stage_inside_the_transaction_then_move_after_commit(self):
        old = self.ind.number
        result = self._rename()
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self._number(), "G1-2119")
        self.assertEqual(
            self.calls,
            [
                ("copy", f"{old}/certificate.pdf", "~G1-2119/certificate.pdf", True),
                ("copy", "~G1-2119/certificate.pdf", "G1-2119/certificate.pdf", False),
                ("delete", f"{old}/certificate.pdf", False),
                ("delete", "~G1-2119/certificate.pdf", False),
            ],
            "only the staging copy runs inside the transaction",
        )

    def test_copy_failure_rolls_the_rename_back(self):
        self.client.copy_object.side_effect = RuntimeError("S3 nere")
        result = self._rename()
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(self._number(), self.ind.number, "the new number is not committed")
        self.client.delete_object.assert_not_called()

    def test_herd_tracking_refusal_never_touches_s3(self):
        result = self._rename(yearly_report_date="2020-01-01")  # before the latest active row → 409
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result.get("problem_status"), 409, result)
        self.assertEqual(self._number(), self.ind.number)
        self.client.copy_object.assert_not_called()
        self.client.delete_object.assert_not_called()
