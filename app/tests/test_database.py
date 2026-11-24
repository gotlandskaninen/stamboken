#!/usr/bin/env python3
"""
Unit tests for the herdbook endpoints.

isort:skip_file
"""
# Fairly lax pylint settings as we want to test a lot of things

# pylint: disable=too-many-public-methods
# pylint: disable=too-many-statements

import inspect
import threading
import time
from datetime import date, datetime

import peewee
import utils.data_access as da

# pylint: disable=import-error
import utils.database as db

# pylint: disable=import-error
from tests.database_test import DatabaseTest, rewind_migrations
from tests.ht_helpers import herd_members


# jscpd:ignore-start
# pylint: disable=too-few-public-methods
class TestDatabaseMapping(DatabaseTest):
    """
    Checks that the database mapping is valid.
    """

    def test_genebank(self):
        """
        Checks that the database tables exists and that SELECT queries work
        using the db.verify() function.
        """
        self.assertTrue(db.verify(False))


class TestDatabase(DatabaseTest):
    """
    Checks that the functions and classes in database.py are working as
    intended.
    """

    # Uncomment for Max diff
    # maxDiff = None

    def test_genebank(self):
        """
        Checks the database.Genebank class.
        """
        # .short_info()
        gb0_info = self.genebanks[0].short_info()
        gb0_expected = {
            "id": self.genebanks[0].id,
            "name": self.genebanks[0].name,
            "herds": [
                {
                    "id": self.herds[0].id,
                    "herd": self.herds[0].herd,
                    "genebank": self.genebanks[0].id,
                    "herd_name": self.herds[0].herd_name,
                    "is_active": self.herds[0].is_active,
                },
                {
                    "id": self.herds[1].id,
                    "herd": self.herds[1].herd,
                    "genebank": self.genebanks[0].id,
                    "herd_name": self.herds[1].herd_name,
                    "is_active": self.herds[1].is_active,
                },
            ],
        }
        self.assertDictEqual(gb0_info, gb0_expected)

        gb1_info = self.genebanks[1].short_info()
        gb1_expected = {
            "id": self.genebanks[1].id,
            "name": self.genebanks[1].name,
            "herds": [
                {
                    "id": self.herds[2].id,
                    "herd": self.herds[2].herd,
                    "genebank": self.genebanks[1].id,
                    "herd_name": self.herds[2].herd_name,
                    "is_active": self.herds[2].is_active,
                },
            ],
        }
        self.assertDictEqual(gb1_info, gb1_expected)

        # .get_herds()
        # This function is permission dependent, so it needs to be tested for
        # each user. We just test this with genebank0 for now, as I'm lazy.

        def all_herd_fields(index):
            """
            Returns a dict with all herd fields except 'email_validated'.
            We can't use the as_dict() function here, as it doesn't return
            fields where the value is None.
            """
            return {
                "id": self.herds[index].id,
                "genebank": self.herds[index].__dict__["__data__"]["genebank"],
                "herd": self.herds[index].herd,
                "herd_name": self.herds[index].herd_name,
                "is_active": self.herds[index].is_active,
                "start_date": self.herds[index].start_date,
                "name": self.herds[index].name,
                "name_privacy": self.herds[index].name_privacy,
                "physical_address": self.herds[index].physical_address,
                "physical_address_privacy": self.herds[index].physical_address_privacy,
                "location": self.herds[index].location,
                "location_privacy": self.herds[index].location_privacy,
                "email": self.herds[index].email,
                "email_privacy": self.herds[index].email_privacy,
                "www": self.herds[index].www,
                "www_privacy": self.herds[index].www_privacy,
                "mobile_phone": self.herds[index].mobile_phone,
                "mobile_phone_privacy": self.herds[index].mobile_phone_privacy,
                "wire_phone": self.herds[index].wire_phone,
                "wire_phone_privacy": self.herds[index].wire_phone_privacy,
                "latitude": self.herds[index].latitude,
                "longitude": self.herds[index].longitude,
                "coordinates_privacy": self.herds[index].coordinates_privacy,
                "bank_account_number": self.herds[index].bank_account_number,
                "bank_account_number_privacy": self.herds[index].bank_account_number_privacy,
                "bank_name": self.herds[index].bank_name,
                "bank_name_privacy": self.herds[index].bank_name_privacy,
            }

        # admin
        gb0_herds = self.genebanks[0].get_herds(self.admin)
        gb0_expected = [all_herd_fields(0), all_herd_fields(1)]

        self.assertDictEqual(gb0_herds[0], gb0_expected[0])
        self.assertDictEqual(gb0_herds[1], gb0_expected[1])

        # manager
        gb0_herds = self.genebanks[0].get_herds(self.manager)
        self.assertDictEqual(gb0_herds[0], gb0_expected[0])
        self.assertDictEqual(gb0_herds[1], gb0_expected[1])

        # owner / authenticated
        gb0_herds = self.genebanks[0].get_herds(self.owner)

        del gb0_expected[1]["name_privacy"]
        del gb0_expected[1]["physical_address"]
        del gb0_expected[1]["physical_address_privacy"]
        del gb0_expected[1]["location"]
        del gb0_expected[1]["location_privacy"]
        del gb0_expected[1]["www"]
        del gb0_expected[1]["www_privacy"]
        del gb0_expected[1]["mobile_phone"]
        del gb0_expected[1]["mobile_phone_privacy"]
        del gb0_expected[1]["wire_phone"]
        del gb0_expected[1]["wire_phone_privacy"]
        del gb0_expected[1]["latitude"]
        del gb0_expected[1]["longitude"]
        del gb0_expected[1]["coordinates_privacy"]
        del gb0_expected[1]["email_privacy"]
        del gb0_expected[1]["bank_account_number"]
        del gb0_expected[1]["bank_account_number_privacy"]
        del gb0_expected[1]["bank_name"]
        del gb0_expected[1]["bank_name_privacy"]

        self.assertDictEqual(gb0_herds[0], gb0_expected[0])
        self.assertDictEqual(gb0_herds[1], gb0_expected[1])

        # viewer: 'authenticated' on every herd, i.e. what the owner sees of the other herd
        gb0_herds = self.genebanks[0].get_herds(self.viewer)
        self.assertDictEqual(gb0_herds[1], gb0_expected[1])
        self.assertNotIn("name", gb0_herds[0])  # name_privacy="private"
        self.assertEqual(gb0_herds[0]["email"], "o@h1")  # email_privacy="authenticated"
        self.assertFalse([k for k in gb0_herds[0] if k.endswith("_privacy")])

    def test_herd(self):
        """
        Checks the database.Herd class.
        """
        # members of a herd = individuals whose latest active tracking row is in it,
        # or — with no active row — whose origin herd it is
        g1_expected = [self.parents[0], self.individuals[0], self.individuals[3]]
        g2_expected = [self.parents[1], self.individuals[1]]
        m3_expected = [self.parents[2], self.parents[3], self.individuals[2], self.individuals[4]]

        # Use assertCountEqual since order may vary
        self.assertCountEqual(herd_members(self.herds[0]), g1_expected)
        self.assertCountEqual(herd_members(self.herds[1]), g2_expected)
        self.assertCountEqual(herd_members(self.herds[2]), m3_expected)

        # .short_info()
        for herd in self.herds:
            expected = {
                "id": herd.id,
                "herd": herd.herd,
                "genebank": herd.__dict__["__data__"]["genebank"],
                "herd_name": herd.herd_name,
                "is_active": herd.is_active,
            }
            self.assertDictEqual(herd.short_info(), expected)

        # .filtered_dict()

        # admin
        h0_result = self.herds[0].filtered_dict(self.admin)
        h1_result = self.herds[1].filtered_dict(self.admin)
        h0_expected = self.herds[0].as_dict()
        h1_expected = self.herds[1].as_dict()

        # the contact object (#117) comes on top of the plain row, for those entitled to it
        for result in (h0_result, h1_result):
            self.assertEqual(result.pop("contact")["mode"], "ej_jamford")
        self.assertDictEqual(h0_result, h0_expected)
        self.assertDictEqual(h1_result, h1_expected)

        # manager
        h0_result = self.herds[0].filtered_dict(self.manager)
        h1_result = self.herds[1].filtered_dict(self.manager)
        for result in (h0_result, h1_result):
            result.pop("contact")
        self.assertDictEqual(h0_result, h0_expected)
        self.assertDictEqual(h1_result, h1_expected)

        # viewer: reads like any logged-in member ('authenticated'), not 'private'
        h0_result = self.herds[0].filtered_dict(self.viewer)
        h1_result = self.herds[1].filtered_dict(self.viewer)
        self.assertEqual(h0_result["email"], "o@h1")  # email_privacy="authenticated"
        self.assertNotIn("name", h0_result)  # name_privacy="private"
        self.assertEqual(h1_result["name"], "owner2")  # name_privacy="authenticated"
        self.assertNotIn("www", h1_result)  # www_privacy="private"
        for result in (h0_result, h1_result):
            self.assertFalse([k for k in result if k.endswith("_privacy")])

        # owner / authenticated
        h0_result = self.herds[0].filtered_dict(self.owner)
        h1_result = self.herds[1].filtered_dict(self.owner)

        filtered_fields = [
            "name_privacy",
            "physical_address",
            "physical_address_privacy",
            "location",
            "location_privacy",
            "www",
            "www_privacy",
            "mobile_phone",
            "mobile_phone_privacy",
            "wire_phone",
            "wire_phone_privacy",
            "latitude",
            "longitude",
            "coordinates_privacy",
            "email_privacy",
            "bank_account_number",
            "bank_account_number_privacy",
            "bank_name",
            "bank_name_privacy",
        ]

        # remove fields that non-owners can't access
        for field in filtered_fields:
            if field in h1_expected:
                del h1_expected[field]

        self.assertEqual(set(h0_result.pop("contact")), {"rows"})  # the owner's own rows, nothing fetched
        self.assertNotIn("contact", h1_result)  # not the owner's herd
        self.assertDictEqual(h0_result, h0_expected)
        self.assertDictEqual(h1_result, h1_expected)

    def test_remove_fields_by_privacy_unknown_value_is_private(self):
        """A stored value outside public/authenticated/private reads as 'private'; it never raises."""
        data = {
            "email": "x",
            "email_privacy": "hemlig",
            "latitude": 59,
            "longitude": 17,
            "coordinates_privacy": "hemlig",
            "www": "w",
            "www_privacy": "public",
        }

        def read(access_level):
            try:
                return db.remove_fields_by_privacy(data, access_level)
            except ValueError as exc:
                self.fail(f"unknown privacy value raised {exc!r} at access level {access_level!r}")

        self.assertEqual(read("public"), {"www": "w"})
        self.assertEqual(read("authenticated"), {"www": "w"})
        self.assertEqual(read("private"), data)

    def test_herd_with_unknown_privacy_value_still_reads(self):
        """One bad *_privacy value must not break herd reads for anyone, admins included."""
        self.herds[0].email_privacy = "hemlig"
        self.herds[0].save()
        for user, sees_email in ((self.admin, True), (self.manager, True), (self.owner, True), (self.viewer, False)):
            try:
                herd = self.herds[0].filtered_dict(user)
                herds = self.genebanks[0].get_herds(user)
            except ValueError as exc:
                self.fail(f"{user.email}: herd read raised {exc!r}")
            self.assertEqual("email" in herd, sees_email, user.email)
            self.assertEqual(len(herds), 2)

    def test_color(self):
        """
        Checks the database.Color class.

        Currently there are no functions on this class to test, so we stick to
        verifying the table.
        """
        self.assertTrue(db.Color.table_exists())

    def test_breeding(self):
        """
        Checks the database.Breeding class.

        Currently there are no functions on this class to test, so we stick to
        verifying the table.
        """
        self.assertTrue(db.Breeding.table_exists())

    def test_individual(self):
        """
        Checks the database.Individual class.
        """
        self.assertTrue(db.Individual.table_exists())

        # .current_herd
        self.assertEqual(self.individuals[0].current_herd.id, self.herds[0].id)
        self.assertEqual(self.individuals[1].current_herd.id, self.herds[1].id)
        self.assertEqual(self.individuals[2].current_herd.id, self.herds[2].id)

        # .children (sort by number for consistent comparison across databases)
        def sort_by_number(individuals):
            return sorted(individuals, key=lambda x: x.number)

        self.assertListEqual(
            sort_by_number(self.parents[0].children),
            sort_by_number(
                [
                    self.individuals[1],
                    self.individuals[0],
                    self.individuals[3],
                ]
            ),
        )
        self.assertListEqual(
            sort_by_number(self.parents[1].children),
            sort_by_number(
                [
                    self.individuals[0],
                    self.individuals[3],
                    self.individuals[1],
                ]
            ),
        )
        self.assertListEqual(
            sort_by_number(self.parents[2].children),
            sort_by_number([self.individuals[2], self.individuals[4]]),
        )
        self.assertListEqual(
            sort_by_number(self.parents[3].children),
            sort_by_number([self.individuals[2], self.individuals[4]]),
        )

        # .as_dict()
        mother = {
            "id": self.parents[0].id,
            "name": self.parents[0].name,
            "number": self.parents[0].number,
        }
        father = {
            "id": self.parents[1].id,
            "name": self.parents[1].name,
            "number": self.parents[1].number,
        }

        # pylint: disable=bad-super-call
        data = super(db.Individual, self.individuals[0]).as_dict()
        data["genebank_id"] = self.genebanks[0].id
        data["genebank"] = self.genebanks[0].name
        data["origin_herd"] = {
            "id": self.herds[0].id,
            "herd": self.herds[0].herd,
            "herd_name": self.herds[0].herd_name,
        }
        data["herd"] = {
            "id": self.herds[0].id,
            "herd": self.herds[0].herd,
            "herd_name": self.herds[0].herd_name,
        }

        data["birth_date"] = self.breeding[0].birth_date.strftime("%Y-%m-%d")
        data["litter_size"] = self.breeding[0].litter_size
        data["litter_size6w"] = self.breeding[0].litter_size6w

        data["mother"] = mother
        data["father"] = father
        data["color"] = self.colors[0].name
        data["color_id"] = self.colors[0].id
        data["alive"] = not self.individuals[0].death_date and not self.individuals[0].death_note
        data["is_active"] = False
        data["is_registered"] = bool(self.individuals[0].certificate or self.individuals[0].digital_certificate)
        data["weights"] = [
            {
                "weight": self.weights[0].weight,
                "date": self.weights[0].weight_date.strftime("%Y-%m-%d"),
            }
        ]
        data["bodyfat"] = [
            {
                "bodyfat": self.bodyfat[0].bodyfat,
                "date": self.bodyfat[0].bodyfat_date.strftime("%Y-%m-%d"),
            }
        ]
        data["herd_tracking"] = [
            {
                "herd_id": self.herd_tracking[0].herd.id,
                "herd": self.herd_tracking[0].herd.herd,
                "herd_name": self.herd_tracking[0].herd.herd_name,
                "date": self.herd_tracking[0].herd_tracking_date.strftime("%Y-%m-%d"),
                "kind": self.herd_tracking[0].kind,
            }
        ]

        data.pop("updated_at", None)  # Internal field, excluded from as_dict()
        self.assertDictEqual(self.individuals[0].as_dict(), data)

        # .list_info()
        for individual in self.individuals:
            expected_list_info = super(db.Individual, individual).as_dict()
            expected_list_info.pop("updated_at", None)
            self.assertDictEqual(individual.list_info(), expected_list_info)

        # .short_info()
        for individual in self.individuals:
            mother = {
                "id": individual.breeding.mother.id,
                "number": individual.breeding.mother.number,
            }
            father = {
                "id": individual.breeding.father.id,
                "number": individual.breeding.father.number,
            }

            # Explicit per fixture (the rule itself is pinned in test_herd_tracking_model.py): the
            # fixture herds are inactive, which alone makes all five fixture rabbits inactive.
            is_active = False

            self.assertDictEqual(
                individual.short_info(),
                {
                    "id": individual.id,
                    "name": individual.name,
                    "is_active": is_active,
                    "number": individual.number,
                    "sex": individual.sex,
                    "father": father,
                    "mother": mother,
                },
            )

    def test_short_info_active_when_every_requirement_holds(self):
        """Counterpart to the all-inactive fixture: certificate + active holder herd + recent life sign."""
        individual = self.individuals[2]  # latest row: TRANSFER 30 days ago into herds[2]
        self.assertFalse(individual.short_info()["is_active"])
        db.Herd.update(is_active=True).where(db.Herd.id == self.herds[2].id).execute()
        db.Individual.update(certificate="99").where(db.Individual.id == individual.id).execute()
        self.assertTrue(db.Individual.get_by_id(individual.id).short_info()["is_active"])

    def test_individual_file(self):
        """
        Checks the database.IndividualFile class.

        Currently there are no functions on this class to test, so we stick to
        verifying the table.
        """
        self.assertTrue(db.IndividualFile.table_exists())

    def test_disease(self):
        """
        Checks the database.Disease class.

        Currently there are no functions on this class to test, so we stick to
        verifying the table.
        """
        self.assertTrue(db.Disease.table_exists())

    def test_individual_disease(self):
        """
        Checks the database.IndividualDisease class.

        Currently there are no functions on this class to test, so we stick to
        verifying the table.
        """
        self.assertTrue(db.IndividualDisease.table_exists())

    def test_weight(self):
        """
        Checks the database.Weight class.

        Currently there are no functions on this class to test, so we stick to
        verifying the table.
        """
        self.assertTrue(db.Weight.table_exists())

    def test_bodyfat(self):
        """
        Checks the database.Bodyfat class.

        Currently there are no functions on this class to test, so we stick to
        verifying the table.
        """
        self.assertTrue(db.Bodyfat.table_exists())

    # user has a lot of things to test, so it's split in several tests
    def test_user_privileges(self):
        """
        Tests the database.User.privileges function.
        """
        # .privileges (getter and setter is tested through other functions)
        self.assertListEqual(self.admin.privileges, [{"level": "admin"}])
        self.assertListEqual(
            self.manager.privileges,
            [{"level": "manager", "genebank": self.genebanks[0].id}],
        )
        self.assertListEqual(
            self.viewer.privileges,
            [{"level": "viewer", "genebank": self.genebanks[0].id}],
        )
        self.assertListEqual(self.owner.privileges, [{"level": "owner", "herd": self.herds[0].id}])

    def test_user_has_role(self):
        """
        Tests the database.User.has_role function.
        """
        self.assertEqual(self.admin.has_role("admin"), True)
        self.assertEqual(self.manager.has_role("admin"), False)
        self.assertEqual(self.viewer.has_role("admin"), False)
        self.assertEqual(self.owner.has_role("admin"), False)

        self.assertEqual(self.admin.has_role("manager", self.genebanks[0].id), False)
        self.assertEqual(self.manager.has_role("manager", self.genebanks[0].id), True)
        self.assertEqual(self.viewer.has_role("manager", self.genebanks[0].id), False)
        self.assertEqual(self.owner.has_role("manager", self.genebanks[0].id), False)
        self.assertEqual(self.admin.has_role("manager", self.genebanks[1].id), False)
        self.assertEqual(self.manager.has_role("manager", self.genebanks[1].id), False)
        self.assertEqual(self.viewer.has_role("manager", self.genebanks[1].id), False)
        self.assertEqual(self.owner.has_role("manager", self.genebanks[1].id), False)

        self.assertEqual(self.admin.has_role("viewer", self.genebanks[0].id), False)
        self.assertEqual(self.manager.has_role("viewer", self.genebanks[0].id), False)
        self.assertEqual(self.viewer.has_role("viewer", self.genebanks[0].id), True)
        self.assertEqual(self.owner.has_role("viewer", self.genebanks[0].id), False)
        self.assertEqual(self.admin.has_role("viewer", self.genebanks[1].id), False)
        self.assertEqual(self.manager.has_role("viewer", self.genebanks[1].id), False)
        self.assertEqual(self.viewer.has_role("viewer", self.genebanks[1].id), False)
        self.assertEqual(self.owner.has_role("viewer", self.genebanks[1].id), False)

        self.assertEqual(self.admin.has_role("owner", self.herds[0].id), False)
        self.assertEqual(self.manager.has_role("owner", self.herds[0].id), False)
        self.assertEqual(self.viewer.has_role("owner", self.herds[0].id), False)
        self.assertEqual(self.owner.has_role("owner", self.herds[0].id), True)
        self.assertEqual(self.admin.has_role("owner", self.herds[1].id), False)
        self.assertEqual(self.manager.has_role("owner", self.herds[1].id), False)
        self.assertEqual(self.viewer.has_role("owner", self.herds[1].id), False)
        self.assertEqual(self.owner.has_role("owner", self.herds[1].id), False)

    def test_user_change_roles(self):
        """
        Tests the database.User.add_role and remove_role functions.
        """
        user = da.register_user("test", "pass")
        user.add_role("admin")
        self.assertEqual(user.has_role("admin"), True)
        self.assertEqual(user.has_role("manager", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("manager", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("owner", self.herds[0].id), False)
        self.assertEqual(user.has_role("owner", self.herds[1].id), False)

        user.add_role("manager", self.genebanks[0].id)
        self.assertEqual(user.has_role("admin"), True)
        self.assertEqual(user.has_role("manager", self.genebanks[0].id), True)
        self.assertEqual(user.has_role("manager", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("owner", self.herds[0].id), False)
        self.assertEqual(user.has_role("owner", self.herds[1].id), False)

        user.add_role("viewer", self.genebanks[1].id)
        self.assertEqual(user.has_role("admin"), True)
        self.assertEqual(user.has_role("manager", self.genebanks[0].id), True)
        self.assertEqual(user.has_role("manager", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[1].id), True)
        self.assertEqual(user.has_role("owner", self.herds[0].id), False)
        self.assertEqual(user.has_role("owner", self.herds[1].id), False)

        user.add_role("owner", self.herds[1].id)
        self.assertEqual(user.has_role("admin"), True)
        self.assertEqual(user.has_role("manager", self.genebanks[0].id), True)
        self.assertEqual(user.has_role("manager", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[1].id), True)
        self.assertEqual(user.has_role("owner", self.herds[0].id), False)
        self.assertEqual(user.has_role("owner", self.herds[1].id), True)

        # remove roles
        user.remove_role("owner", self.herds[1].id)
        self.assertEqual(user.has_role("admin"), True)
        self.assertEqual(user.has_role("manager", self.genebanks[0].id), True)
        self.assertEqual(user.has_role("manager", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[1].id), True)
        self.assertEqual(user.has_role("owner", self.herds[0].id), False)
        self.assertEqual(user.has_role("owner", self.herds[1].id), False)
        user.remove_role("manager", self.genebanks[0].id)
        self.assertEqual(user.has_role("admin"), True)
        self.assertEqual(user.has_role("manager", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("manager", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[1].id), True)
        self.assertEqual(user.has_role("owner", self.herds[0].id), False)
        self.assertEqual(user.has_role("owner", self.herds[1].id), False)
        user.remove_role("viewer", self.genebanks[1].id)
        self.assertEqual(user.has_role("admin"), True)
        self.assertEqual(user.has_role("manager", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("manager", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("owner", self.herds[0].id), False)
        self.assertEqual(user.has_role("owner", self.herds[1].id), False)
        user.remove_role("admin")
        self.assertEqual(user.has_role("admin"), False)
        self.assertEqual(user.has_role("manager", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("manager", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[0].id), False)
        self.assertEqual(user.has_role("viewer", self.genebanks[1].id), False)
        self.assertEqual(user.has_role("owner", self.herds[0].id), False)
        self.assertEqual(user.has_role("owner", self.herds[1].id), False)

    def test_user_is_admin(self):
        """
        Tests the database.User.is_admin property.
        """
        self.assertEqual(self.admin.is_admin, True)
        self.assertEqual(self.manager.is_admin, False)
        self.assertEqual(self.viewer.is_admin, False)
        self.assertEqual(self.owner.is_admin, False)

    def test_user_is_manager(self):
        """
        Tests the database.User.is_manager property.
        """
        self.assertEqual(self.admin.is_manager, None)
        self.assertEqual(self.manager.is_manager, [self.genebanks[0].id])
        self.assertEqual(self.viewer.is_manager, None)
        self.assertEqual(self.owner.is_manager, None)

    def test_user_is_owner(self):
        """
        Tests the database.User.is_owner property.
        """
        self.assertEqual(self.admin.is_owner, None)
        self.assertEqual(self.manager.is_owner, None)
        self.assertEqual(self.viewer.is_owner, None)
        self.assertEqual(self.owner.is_owner, [self.herds[0].herd])

    def test_user_accessible_genebanks(self):
        """
        Tests the database.User.accessible_genebanks property.
        """
        self.assertEqual(
            self.admin.accessible_genebanks,
            [self.genebanks[0].id, self.genebanks[1].id],
        )
        self.assertEqual(self.manager.accessible_genebanks, [self.genebanks[0].id])
        self.assertEqual(self.viewer.accessible_genebanks, [self.genebanks[0].id])
        self.assertEqual(self.owner.accessible_genebanks, [self.genebanks[0].id])

    def test_user_frontend_data(self):
        """
        Tests the database.User.frontend_data function.
        """
        self.assertDictEqual(
            self.admin.frontend_data(),
            {
                "id": self.admin.id,
                "email": "admin",
                "username": None,
                "fullname": None,
                "validated": False,
                "is_admin": True,
                "is_matrikel_admin": False,
                "is_manager": None,
                "is_owner": None,
                "profile_picture": None,
                "google_picture": None,
                "google_name": None,
                "google_email": None,
                "use_google_picture": True,
                # Admins are implicitly promoted regardless of the stored flag
                "v2_prod_access": True,
            },
        )
        self.assertDictEqual(
            self.manager.frontend_data(),
            {
                "id": self.manager.id,
                "email": "man",
                "username": None,
                "fullname": None,
                "validated": False,
                "is_admin": False,
                "is_matrikel_admin": False,
                "is_manager": [self.genebanks[0].id],
                "is_owner": None,
                "profile_picture": None,
                "google_picture": None,
                "google_name": None,
                "google_email": None,
                "use_google_picture": True,
                "v2_prod_access": False,
            },
        )
        self.assertDictEqual(
            self.viewer.frontend_data(),
            {
                "id": self.viewer.id,
                "email": "spec",
                "username": None,
                "fullname": None,
                "validated": False,
                "is_admin": False,
                "is_matrikel_admin": False,
                "is_manager": None,
                "is_owner": None,
                "profile_picture": None,
                "google_picture": None,
                "google_name": None,
                "google_email": None,
                "use_google_picture": True,
                "v2_prod_access": False,
            },
        )
        self.assertDictEqual(
            self.owner.frontend_data(),
            {
                "id": self.owner.id,
                "email": "owner",
                "username": None,
                "fullname": None,
                "validated": False,
                "is_admin": False,
                "is_matrikel_admin": False,
                "is_manager": None,
                "is_owner": [self.herds[0].herd],
                "profile_picture": None,
                "google_picture": None,
                "google_name": None,
                "google_email": None,
                "use_google_picture": True,
                "v2_prod_access": False,
            },
        )

    def test_user_get_genebanks(self):
        """
        Tests the database.User.get_genebanks function.
        """
        # object reference comparison is intentional here
        self.assertListEqual(self.admin.get_genebanks(), self.genebanks)
        self.assertListEqual(self.manager.get_genebanks(), [self.genebanks[0]])
        self.assertListEqual(self.viewer.get_genebanks(), [self.genebanks[0]])
        self.assertListEqual(self.owner.get_genebanks(), [self.genebanks[0]])

    def test_user_get_genebank(self):
        """
        Tests the database.User.get_genebank function.
        """
        g_0 = self.genebanks[0].as_dict()
        g_1 = self.genebanks[1].as_dict()
        # we trust genebank.get_herds() as we tested it
        g_0["herds"] = self.genebanks[0].get_herds(self.admin)
        g_1["herds"] = self.genebanks[1].get_herds(self.admin)
        self.assertDictEqual(self.admin.get_genebank(self.genebanks[0].id), g_0)
        self.assertDictEqual(self.admin.get_genebank(self.genebanks[1].id), g_1)
        g_0["herds"] = self.genebanks[0].get_herds(self.manager)
        self.assertDictEqual(self.manager.get_genebank(self.genebanks[0].id), g_0)
        self.assertEqual(self.manager.get_genebank(self.genebanks[1].id), None)
        g_0["herds"] = self.genebanks[0].get_herds(self.viewer)
        self.assertDictEqual(self.viewer.get_genebank(self.genebanks[0].id), g_0)
        self.assertEqual(self.viewer.get_genebank(self.genebanks[1].id), None)
        g_0["herds"] = self.genebanks[0].get_herds(self.owner)
        self.assertDictEqual(self.owner.get_genebank(self.genebanks[0].id), g_0)
        self.assertEqual(self.owner.get_genebank(self.genebanks[1].id), None)

    def test_user_can_edit(self):
        """
        Tests the database.User.can_edit function.
        """
        self.assertEqual(self.admin.can_edit("Gotland"), True)
        self.assertEqual(self.admin.can_edit("Mellerud"), True)
        self.assertEqual(self.admin.can_edit("G1"), True)
        self.assertEqual(self.admin.can_edit("G2"), True)
        self.assertEqual(self.admin.can_edit("M3"), True)
        self.assertEqual(self.admin.can_edit("G1-1911"), True)
        self.assertEqual(self.admin.can_edit("G2-1711"), True)
        self.assertEqual(self.admin.can_edit("M3-1811"), True)

        self.assertEqual(self.manager.can_edit("Gotland"), True)
        self.assertEqual(self.manager.can_edit("Mellerud"), False)
        self.assertEqual(self.manager.can_edit("G1"), True)
        self.assertEqual(self.manager.can_edit("G2"), True)
        self.assertEqual(self.manager.can_edit("M3"), False)
        self.assertEqual(self.manager.can_edit("G1-1911"), True)
        self.assertEqual(self.manager.can_edit("G2-1711"), True)
        self.assertEqual(self.manager.can_edit("M3-1811"), False)

        self.assertEqual(self.viewer.can_edit("Gotland"), False)
        self.assertEqual(self.viewer.can_edit("Mellerud"), False)
        self.assertEqual(self.viewer.can_edit("G1"), False)
        self.assertEqual(self.viewer.can_edit("G2"), False)
        self.assertEqual(self.viewer.can_edit("G3"), False)
        self.assertEqual(self.viewer.can_edit("G1-1911"), False)
        self.assertEqual(self.viewer.can_edit("G2-1711"), False)
        self.assertEqual(self.viewer.can_edit("M3-1811"), False)

        self.assertEqual(self.owner.can_edit("Gotland"), False)
        self.assertEqual(self.owner.can_edit("Mellerud"), False)
        self.assertEqual(self.owner.can_edit("G1"), True)
        self.assertEqual(self.owner.can_edit("G2"), False)
        self.assertEqual(self.owner.can_edit("M3"), False)
        self.assertEqual(self.owner.can_edit("G1-1911"), True)
        self.assertEqual(self.owner.can_edit("G2-1711"), False)
        self.assertEqual(self.owner.can_edit("M3-1811"), False)

    def test_user_message(self):
        """
        Checks the database.UserMessage class.

        Currently there are no functions on this class to test, so we stick to
        verifying the table.
        """
        self.assertTrue(db.UserMessage.table_exists())

    def test_yearly_herd_report(self):
        """
        Checks the database.YearlyHerdReport class.

        Currently there are no functions on this class to test, so we stick to
        verifying the table.
        """
        self.assertTrue(db.YearlyHerdReport.table_exists())

    def test_yearly_report_round(self):
        """
        Checks the database.YearlyReportRound class.

        Currently there are no functions on this class to test, so we stick to
        verifying the table.
        """
        self.assertTrue(db.YearlyReportRound.table_exists())

    def test_herd_tracking(self):
        """
        Checks the database.HerdTracking class.

        Currently there are no functions on this class to test, so we stick to
        verifying the table.
        """
        self.assertTrue(db.HerdTracking.table_exists())


# pylint: disable=too-few-public-methods
class TestDatabaseMigration(DatabaseTest):
    """
    Checks that the database migrations works
    """

    def test_no_table(self):
        """
        Checks that the schema migration works from very old version.
        Will also run through all migrations.
        """
        rewind_migrations(1)
        db.SchemaHistory.drop_table()

        db.check_migrations()
        self.assertTrue(db.SchemaHistory.table_exists())
        self.assertEqual(
            db.SchemaHistory.select(  # pylint: disable=E1120
                db.fn.MAX(db.SchemaHistory.version)
            ).scalar(),
            db.CURRENT_SCHEMA_VERSION,
        )

    def test_last_migration(self):
        """
        Replays the last migration
        """

        rewind_migrations(db.CURRENT_SCHEMA_VERSION)

        db.check_migrations()
        self.assertTrue(db.SchemaHistory.table_exists())
        self.assertEqual(
            db.SchemaHistory.select(  # pylint: disable=E1120
                db.fn.MAX(db.SchemaHistory.version)
            ).scalar(),
            db.CURRENT_SCHEMA_VERSION,
        )

    def test_replay_30_to_31_creates_genetics_version(self):
        """
        A database stamped at 30 without the genetics guards gets the version row
        and all nine deferred triggers from the 30→31 replay (not from init()).
        """
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("genetics version triggers require PostgreSQL")
        self.addCleanup(db.check_migrations)

        rewind_migrations(31)
        if db.SchemaHistory.get_or_none(db.SchemaHistory.version == 30) is None:
            db.SchemaHistory.insert(  # pylint: disable=E1120
                version=30, comment="test seed", applied=datetime.now()
            ).execute()
        for table in db._GENETICS_UPDATE_COLUMNS:  # pylint: disable=protected-access
            db.DATABASE.execute_sql(f'DROP TRIGGER IF EXISTS "genetics_change_{table}_iud" ON "{table}"')
            db.DATABASE.execute_sql(f'DROP TRIGGER IF EXISTS "genetics_change_{table}_upd" ON "{table}"')
        db.DATABASE.execute_sql("DROP TABLE genetics_version")

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        rows = db.DATABASE.execute_sql("SELECT tgname FROM pg_trigger WHERE tgname LIKE 'genetics_change_%%'")
        tables = ("individual", "breeding", "herd", "herd_tracking", "yearlyreportround")
        expected = {f"genetics_change_{t}_iud" for t in tables}
        expected |= {f"genetics_change_{t}_upd" for t in tables if t != "herd_tracking"}
        self.assertEqual({r[0] for r in rows}, expected)
        self.assertEqual(db.DATABASE.execute_sql("SELECT count(*) FROM genetics_version").fetchone()[0], 1)

    def test_replay_31_to_32_reshapes_history(self):
        """
        A database stamped at 31 with an old-style history table and one row
        migrates to 32: the row is gone, the new columns and state table exist,
        and the history index names equal a fresh bootstrap's.
        """
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("index introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        table = db.GeneticMetricsHistory._meta.table_name

        def restore_model_table():
            db.GeneticMetricsHistory.drop_table(safe=True)
            db.GeneticMetricsHistory.create_table()
            dtype = db.DATABASE.execute_sql(
                "SELECT data_type FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
                (table, "mean_inbreeding"),
            ).fetchone()[0]
            self.assertEqual(dtype, "real")

        self.addCleanup(restore_model_table)  # runs before check_migrations

        def index_names():
            return {i.name for i in db.DATABASE.get_indexes(table)}

        fresh = index_names()

        rewind_migrations(32)
        # A bootstrapped database holds only the CURRENT row; without a 31 the
        # replay starts from None and 15→16 fails on the old-style table.
        if db.SchemaHistory.get_or_none(db.SchemaHistory.version == 31) is None:
            db.SchemaHistory.insert(  # pylint: disable=E1120
                version=31, comment="test seed", applied=datetime.now()
            ).execute()
        db.DATABASE.execute_sql("DROP TABLE IF EXISTS genetics_history_state")
        db.DATABASE.execute_sql(f'DROP TABLE "{table}"')
        db.DATABASE.execute_sql(
            f"""CREATE TABLE "{table}" (
                id SERIAL PRIMARY KEY,
                genebank_id INTEGER NOT NULL REFERENCES genebank (genebank_id),
                snapshot_date DATE NOT NULL,
                population_size INTEGER NOT NULL,
                active_count INTEGER NOT NULL,
                mean_inbreeding DOUBLE PRECISION,
                mean_kinship DOUBLE PRECISION,
                founder_equivalents DOUBLE PRECISION,
                data_quality VARCHAR(10) NOT NULL,
                created_at TIMESTAMP NOT NULL)"""
        )
        db.DATABASE.execute_sql(
            f'CREATE UNIQUE INDEX "{table}_genebank_id_snapshot_date" ON "{table}" (genebank_id, snapshot_date)'
        )
        db.DATABASE.execute_sql(f'CREATE INDEX "{table}_genebank_id" ON "{table}" (genebank_id)')
        gb = db.Genebank.create(name="Replay32")
        db.DATABASE.execute_sql(
            f'INSERT INTO "{table}" (genebank_id, snapshot_date, population_size, active_count,'
            " data_quality, created_at) VALUES (%s, '2020-12-31', 10, 5, 'high', now())",
            (gb.id,),
        )

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertEqual(db.DATABASE.execute_sql(f'SELECT count(*) FROM "{table}"').fetchone()[0], 0)
        self.assertIn("genetics_history_state", db.DATABASE.get_tables())
        self.assertEqual(index_names(), fresh)
        info = {
            r[0]: r[1]
            for r in db.DATABASE.execute_sql(
                "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = %s", (table,)
            )
        }
        for name in ("report_year", "as_of", "definition_version", "pedigree_version"):
            self.assertEqual(info[name], "NO", name)
        self.assertEqual(info["fge"], "YES")

    def test_replay_33_to_34_adds_the_genetics_epoch(self):
        """A database stamped at 33 gets genetics_version.epoch (random) and rotate_genetics_epoch()."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        rewind_migrations(34)
        db.DATABASE.execute_sql("DROP FUNCTION IF EXISTS rotate_genetics_epoch()")
        db.DATABASE.execute_sql("ALTER TABLE genetics_version DROP COLUMN IF EXISTS epoch")

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertIn("epoch", {c.name for c in db.DATABASE.get_columns("genetics_version")})
        before = db.DATABASE.execute_sql("SELECT epoch FROM genetics_version WHERE id = 1").fetchone()[0]
        self.assertTrue(before)
        self.assertNotEqual(db.rotate_genetics_epoch(), before)

    def test_replay_35_to_36_adds_microchip(self):
        """A database stamped at 35 gets Individual.microchip, which takes 15 digits or NULL."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("check constraints require PostgreSQL")
        self.addCleanup(db.check_migrations)
        rewind_migrations(36)
        db.DATABASE.execute_sql("ALTER TABLE individual DROP COLUMN IF EXISTS microchip")

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        ind = self.individuals[0]
        for chip in ("752098100012345", None):
            db.Individual.update(microchip=chip).where(db.Individual.id == ind.id).execute()
            self.assertEqual(db.Individual.get_by_id(ind.id).microchip, chip)
        for chip in ("", "75209810001234", "7520981000123456", "75209810001234x"):
            with (
                self.subTest(chip=chip),
                self.assertRaises((peewee.IntegrityError, peewee.DataError)),
                db.DATABASE.atomic(),
            ):
                db.Individual.update(microchip=chip).where(db.Individual.id == ind.id).execute()

    def test_replay_36_to_37_adds_billing_address(self):
        """A database stamped at 36 gets the six billing columns on membership and member_application."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        rewind_migrations(37)
        for table in ("membership", "member_application"):
            for column in db.BILLING_FIELDS:
                db.DATABASE.execute_sql(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS "{column}"')

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        for table in ("membership", "member_application"):
            columns = {c.name: c for c in db.DATABASE.get_columns(table)}
            for column in db.BILLING_FIELDS:
                with self.subTest(table=table, column=column):
                    self.assertIn(column, columns)
                    self.assertTrue(columns[column].null)
        ms = db.Membership.create(billing_name="Djurparken i Exempelby", billing_postal_code="123 45")
        self.assertEqual(db.Membership.get_by_id(ms.id).billing_name, "Djurparken i Exempelby")

        # Running it again on the migrated schema changes nothing.
        rewind_migrations(37)
        db.check_migrations()
        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)

    def test_replay_37_to_38_retires_the_pdf_of_a_replaced_digital_certificate(self):
        """
        Before ADR-0019 a paper certificate removed the digital number and left the PDF row current: retired.
        A blank number removed it too, but nothing replaced that certificate: its row stays current and is
        counted. A digital certificate keeps its row.
        """
        self.addCleanup(db.check_migrations)
        replaced, digital, blanked = self.individuals[0], self.individuals[1], self.individuals[2]
        db.Individual.update(certificate="", digital_certificate=None).where(db.Individual.id == blanked.id).execute()
        db.Individual.update(certificate="98765", digital_certificate=None).where(
            db.Individual.id == replaced.id
        ).execute()
        db.Individual.update(certificate=None, digital_certificate=100000).where(
            db.Individual.id == digital.id
        ).execute()
        for ind in (replaced, digital, blanked):
            db.DigitalCertificateV2.create(individual=ind, issued_by=self.admin, file_path="x.pdf", checksum="0" * 64)

        def current(ind):
            return db.DigitalCertificateV2.get(db.DigitalCertificateV2.individual == ind.id).is_current

        for _ in range(2):  # a second run on the repaired rows changes nothing
            rewind_migrations(38)
            db.check_migrations()
            self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
            self.assertEqual((current(replaced), current(digital), current(blanked)), (False, True, True))
            self.assertIn("1 current rows without a number", db.SchemaHistory.get_by_id(38).comment)

    def test_replay_39_to_40_resets_bank_privacy(self):
        """A database stamped at 39 gets every stored bank privacy level reset to private."""
        self.addCleanup(db.check_migrations)
        gb = db.Genebank.create(name="Replay40")
        herd = db.Herd.create(
            genebank=gb, herd="R40", bank_account_number_privacy="public", bank_name_privacy="Public "
        )
        null_herd = db.Herd.create(
            genebank=gb, herd="R40N", bank_account_number_privacy=None, bank_name_privacy="public"
        )  # one NULL next to one non-private column: only the non-NULL one is reset
        rewind_migrations(40)

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        herd = db.Herd.get_by_id(herd.id)
        self.assertEqual(herd.bank_account_number_privacy, "private")
        self.assertEqual(herd.bank_name_privacy, "private")
        null_herd = db.Herd.get_by_id(null_herd.id)
        self.assertIsNone(null_herd.bank_account_number_privacy)  # NULL is left alone
        self.assertEqual(null_herd.bank_name_privacy, "private")
        # The reset writes no audit row (the trigger copies the account number) and the trigger is back on.

        def updates():
            return (
                db.AuditLog.select()
                .where(db.AuditLog.table_name == "herd", db.AuditLog.record_id == str(herd.id))
                .where(db.AuditLog.operation == "UPDATE")
                .count()
            )

        self.assertEqual(updates(), 0)
        db.Herd.update(www="x").where(db.Herd.id == herd.id).execute()
        self.assertEqual(updates(), 1)

    def test_replay_44_to_45_lets_matrikel_audit_go_without_actor(self):
        """A database stamped at 44 accepts matrikel audit rows without a user (the nightly anonymization, #70)."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        db.DATABASE.execute_sql('ALTER TABLE "matrikel_audit" ALTER COLUMN "actor_id" SET NOT NULL')
        rewind_migrations(45)

        for _ in range(2):  # a second run on the migrated schema changes nothing
            db.check_migrations()
            self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
            columns = {c.name: c for c in db.DATABASE.get_columns("matrikel_audit")}
            self.assertTrue(columns["actor_id"].null)
            rewind_migrations(45)
        db.check_migrations()
        membership = db.Membership.create(member_number=4141)
        self.assertIsNone(db.MatrikelAudit.create(actor=None, action="x", membership=membership).actor_id)

    def test_replay_49_to_50_adds_contact_columns(self):
        """A database stamped at 49 gets herd.contact_member_id and herd.contact_pending."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        db.DATABASE.execute_sql("ALTER TABLE herd DROP COLUMN IF EXISTS contact_member_id")
        db.DATABASE.execute_sql("ALTER TABLE herd DROP COLUMN IF EXISTS contact_pending")
        rewind_migrations(50)

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertTrue({"contact_member_id", "contact_pending"} <= {c.name for c in db.DATABASE.get_columns("herd")})

    def test_replay_adds_nullable_membership_organization_fields(self):
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        membership = db.Membership.create(member_number=5101, address="Testgatan 1")
        row = db.Membership.select().where(db.Membership.id == membership.id).dicts()
        before = row.get()
        version = self._migration_version("ORGANIZATION_52")
        db.SchemaHistory.delete().where(db.SchemaHistory.version >= version).execute()
        db.SchemaHistory.get_or_create(
            version=version - 1, defaults={"comment": "test seed", "applied": datetime.now()}
        )
        db.DATABASE.execute_sql("ALTER TABLE membership DROP COLUMN organization_name, DROP COLUMN organization_number")

        db.check_migrations()

        columns = db.DATABASE.execute_sql(
            "SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'membership' "
            "AND column_name IN ('organization_name', 'organization_number') ORDER BY column_name"
        ).fetchall()
        self.assertEqual(
            columns,
            [
                ("organization_name", "character varying", 200, "YES", None),
                ("organization_number", "character varying", 11, "YES", None),
            ],
        )
        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertEqual(row.get(), before)
        self.assertEqual((before["organization_name"], before["organization_number"]), (None, None))

        db.Membership.update(organization_name="Testföreningen").where(db.Membership.id == membership.id).execute()
        db.MIGRATIONS[version - 1, version]()
        self.assertEqual(row.get(), {**before, "organization_name": "Testföreningen"})

    def test_branch_numbered_organization_migration_stops_the_replay(self):
        """A dev database that ran or bootstrapped the organization fields as 51 lacks the yearly report: no 52."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("migration history guard is tested on PostgreSQL")
        for comment in (db.ORGANIZATION_52, "Bootstrapped"):
            with self.subTest(comment=comment):
                self.addCleanup(db.check_migrations)
                self.addCleanup(rewind_migrations, 51)  # LIFO: rewind first, then replay 50 -> 52
                rewind_migrations(52)
                db.SchemaHistory.update(comment=comment).where(db.SchemaHistory.version == 51).execute()
                db.DATABASE.drop_tables(db.ARSRAPPORT_MODELS, cascade=True)

                with self.assertRaisesRegex(RuntimeError, "organization fields as migration 51"):
                    db.check_migrations()
                self.assertEqual(self._max_schema_version(), 51)
                self.doCleanups()

        # main's 51 with its tables replays to 52, also when one report table is missing (verify() restores it)
        for drop_one in (False, True):
            with self.subTest(drop_one=drop_one):
                self.addCleanup(db.check_migrations)
                self.addCleanup(rewind_migrations, 51)
                rewind_migrations(52)
                db.SchemaHistory.update(comment="Bootstrapped").where(db.SchemaHistory.version == 51).execute()
                if drop_one:
                    db.DATABASE.drop_tables([db.SaleProposal], cascade=True)
                db.check_migrations()
                self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
                self.doCleanups()

    def test_replay_49_to_50_keeps_contact_values_out_of_audit(self):
        """After the migration an UPDATE of herd.email is listed in changed_fields without its value."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("trigger requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        gb = db.Genebank.create(name="Replay47a")
        herd = db.Herd.create(genebank=gb, herd="R47A", email="a@example.invalid", herd_name="H")
        rewind_migrations(50)
        db.check_migrations()

        db.DATABASE.execute_sql("UPDATE herd SET email = 'x@example.invalid' WHERE herd_id = %s", (herd.id,))

        entry = (
            db.AuditLog.select()
            .where(db.AuditLog.table_name == "herd", db.AuditLog.record_id == str(herd.id))
            .where(db.AuditLog.operation == "UPDATE")
            .order_by(db.AuditLog.id.desc())
            .get()
        )
        self.assertIn("email", entry.changed_fields)
        self.assertNotIn("email", entry.old_data)
        self.assertNotIn("email", entry.new_data)
        self.assertIn("herd_name", entry.new_data)  # other columns are still snapshotted

    def test_replay_49_to_50_purges_old_herd_contact_values(self):
        """A herd audit row written before the migration loses its contact keys; other rows are untouched."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("trigger requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        old = db.AuditLog.create(
            table_name="herd",
            record_id="990047",
            operation="UPDATE",
            old_data={"email": "a@example.invalid", "www": "w", "herd_name": "H"},
            new_data={"email": "b@example.invalid", "name": "N", "herd_name": "H"},
            changed_fields=["email"],
        )
        other = db.AuditLog.create(
            table_name="genebank", record_id="990047", operation="UPDATE", old_data={"email": "keep"}
        )
        rewind_migrations(50)

        db.check_migrations()

        old = db.AuditLog.get_by_id(old.id)
        self.assertEqual(old.old_data, {"herd_name": "H"})
        self.assertEqual(old.new_data, {"herd_name": "H"})
        self.assertEqual(db.AuditLog.get_by_id(other.id).old_data, {"email": "keep"})
        # the append-only rule is back
        db.DATABASE.execute_sql("UPDATE audit_log SET old_data = '{}' WHERE id = %s", (old.id,))
        self.assertEqual(db.AuditLog.get_by_id(old.id).old_data, {"herd_name": "H"})

    def test_replay_49_to_50_compares_linked_herds(self):
        """A herd linked on version 49 is compared by the replay (contact_pending a list), without its contact
        values in the audit history; a herd without membership is not. Once compared it is never compared again:
        a replay after the breeder answered changes nothing."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("trigger requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        membership = db.Membership.create(member_number=4747, address="Byvägen 1", postal_code="62300", city="Roma")
        main = db.Member.create(
            membership=membership,
            first_name="Anna",
            last_name="Exempel",
            role="huvudmedlem",
            email="anna@example.invalid",
            phone="070-111 11 11",
        )
        gb = db.Genebank.create(name="Replay47d")
        linked = db.Herd.create(
            genebank=gb,
            herd="R47D",
            membership=membership,
            name="Anna Exempel",
            email="anna@example.invalid",
            email_privacy="authenticated",
            mobile_phone="070-999 99 99",
        )
        unlinked = db.Herd.create(genebank=gb, herd="R47E", name="Anna Exempel", email="anna@example.invalid")

        def replay():
            """Replay 49 -> 50 with fields on both ORM models that only later migrations add to the tables."""
            rewind_migrations(50)
            db.DATABASE.execute_sql(
                "ALTER TABLE membership DROP COLUMN organization_name, DROP COLUMN organization_number"
            )
            db.Herd._meta.add_field("added_later", peewee.TextField(null=True))  # pylint: disable=protected-access
            try:
                db.check_migrations()
            finally:
                db.Herd._meta.remove_field("added_later")  # pylint: disable=protected-access

        replay()

        herd = db.Herd.get_by_id(linked.id)
        self.assertEqual((herd.contact_member_id, herd.contact_pending), (main.id, ["mobile_phone"]))
        self.assertEqual((herd.name, herd.email, herd.email_privacy), (None, None, "authenticated"))
        self.assertEqual(herd.physical_address_privacy, None)  # NULL already counts as private
        self.assertIsNone(db.Herd.get_by_id(unlinked.id).contact_pending)
        entry = (
            db.AuditLog.select()
            .where(db.AuditLog.table_name == "herd", db.AuditLog.record_id == str(linked.id))
            .order_by(db.AuditLog.id.desc())
            .get()
        )
        self.assertIn("email", entry.changed_fields)
        self.assertNotIn("email", entry.old_data)

        # the breeder answers "Ja, behåll" for the mobile; the next replay leaves the answer alone
        db.Herd.update(contact_pending=[]).where(db.Herd.id == linked.id).execute()
        replay()
        herd = db.Herd.get_by_id(linked.id)
        self.assertEqual((herd.contact_pending, herd.mobile_phone), ([], "070-999 99 99"))

    def test_replay_49_to_50_leaves_a_paused_membership_uncompared(self):
        """O4: the reads show nothing of a membership that is not active, so the replay compares none of its herds:
        contact_pending stays NULL and the own columns stay. set_membership_status compares them when it is active."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("trigger requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        membership = db.Membership.create(member_number=4748, membership_status="inactive", address="Byvägen 1")
        db.Member.create(
            membership=membership, first_name="Per", last_name="Prov", role="huvudmedlem", email="per@example.invalid"
        )
        own = {"name": "Per Prov", "email": "per@example.invalid", "physical_address": "Byvägen 1||"}
        gb = db.Genebank.create(name="Replay50p")
        herd = db.Herd.create(genebank=gb, herd="R50P", membership=membership, **own)
        rewind_migrations(50)

        db.check_migrations()

        herd = db.Herd.get_by_id(herd.id)
        self.assertEqual((herd.contact_member_id, herd.contact_pending), (None, None))
        self.assertEqual({c: getattr(herd, c) for c in own}, own)

    def test_replay_49_to_50_clears_erased_households(self):
        """FC1: a herd linked to a household whose persons are all erased loses every own contact row, the fixed
        phone and the website too, as on_household_erased does; the rows start hidden and the herd is compared.
        A household whose persons only ended is inactive, so it is left uncompared: the farm's own rows stay."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("trigger requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        gb = db.Genebank.create(name="Replay50e")
        own = {
            "name": "Gårdens Kontakt",
            "email": "gard@example.invalid",
            "mobile_phone": "070-999 99 99",
            "wire_phone": "0498-00 00 00",
            "physical_address": "Gårdsvägen 5|62300|Roma",
            "www": "exempelgarden.invalid",
        }
        shown = {f"{c}_privacy": "public" for c in db.HERD_CONTACT_COLUMNS}
        herds = {}
        for kind, (first, last) in {"erased": ("Borttagen", "person"), "ended": ("Anna", "Exempel")}.items():
            membership = db.Membership.create(member_number=len(herds) + 5050, membership_status="inactive")
            for role in ("huvudmedlem", "familjemedlem"):
                db.Member.create(
                    membership=membership, first_name=first, last_name=last, role=role, end_date=date(2025, 1, 1)
                )
            herds[kind] = db.Herd.create(genebank=gb, herd=f"R50{kind[:2]}", membership=membership, **own, **shown)
        rewind_migrations(50)

        db.check_migrations()

        erased = db.Herd.get_by_id(herds["erased"].id)
        for column in db.HERD_CONTACT_COLUMNS:
            self.assertEqual((getattr(erased, column), getattr(erased, f"{column}_privacy")), (None, "private"), column)
        self.assertEqual((erased.contact_member_id, erased.contact_pending), (None, []))
        ended = db.Herd.get_by_id(herds["ended"].id)
        self.assertEqual({c: getattr(ended, c) for c in own}, own)
        self.assertEqual({c: getattr(ended, c) for c in shown}, shown)
        self.assertIsNone(ended.contact_pending)  # not active: left uncompared

    def test_replay_49_to_50_waits_for_a_locked_membership_row(self):
        """FC3: the migration takes membership in EXCLUSIVE mode, so it waits for a transaction that holds a
        membership row FOR UPDATE (retire_membership, which then writes member and membership) instead of
        taking member first and deadlocking with it."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("table locks require PostgreSQL")
        self.addCleanup(db.check_migrations)
        membership = db.Membership.create(member_number=5052)
        rewind_migrations(50)
        errors = []

        def replay():
            try:
                db.check_migrations()
            except Exception as exception:  # pylint: disable=broad-except
                errors.append(exception)
            finally:
                if not db.DATABASE.is_closed():
                    db.DATABASE.close()

        waiting_sql = "SELECT count(*) FROM pg_locks WHERE relation = 'membership'::regclass AND NOT granted"
        thread = threading.Thread(target=replay)
        waited = False
        with db.DATABASE.atomic():
            db.Membership.select().where(db.Membership.id == membership.id).for_update().get()
            thread.start()
            deadline = time.time() + 10
            while not waited and thread.is_alive() and time.time() < deadline:
                waited = db.DATABASE.execute_sql(waiting_sql).fetchone()[0] > 0
                time.sleep(0.05)
        thread.join(timeout=120)

        self.assertTrue(waited, "the migration should wait for the membership row lock")
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)

    def _contact_member_fk(self):
        return db.DATABASE.execute_sql(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conrelid = 'herd'::regclass AND contype = 'f'"
            " AND pg_get_constraintdef(oid) LIKE '%%contact_member_id%%'"
        ).fetchall()

    def test_contact_member_fk_set_null(self):
        """herd.contact_member_id references member(member_id) ON DELETE SET NULL, after init() and after replay."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("pg_constraint requires PostgreSQL")
        self.addCleanup(db.check_migrations)

        def check():
            rows = self._contact_member_fk()
            self.assertEqual(len(rows), 1, rows)
            self.assertIn("REFERENCES member(member_id)", rows[0][0])
            self.assertIn("ON DELETE SET NULL", rows[0][0])

        check()  # the pytest database was bootstrapped by init()
        db.DATABASE.execute_sql("ALTER TABLE herd DROP CONSTRAINT herd_contact_member_id_fkey")
        rewind_migrations(50)
        db.check_migrations()
        check()

    def test_init_restores_contact_member_fk_after_interrupted_bootstrap(self):
        """A restart after an init() that died before member existed (schema_history empty or missing) adds the FK."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("pg_constraint requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        rows = [(r.version, r.comment, r.applied) for r in db.SchemaHistory.select()]

        def restore():
            db.SchemaHistory.delete().execute()
            for version, comment, applied in rows:
                db.SchemaHistory.insert(version=version, comment=comment, applied=applied).execute()  # pylint: disable=E1120

        for empty_or_missing in ("empty", "missing"):
            with self.subTest(schema_history=empty_or_missing):
                db.DATABASE.execute_sql("ALTER TABLE herd DROP CONSTRAINT IF EXISTS herd_contact_member_id_fkey")
                if empty_or_missing == "empty":
                    db.SchemaHistory.delete().execute()
                else:
                    db.SchemaHistory.drop_table()
                db.init()
                self.assertEqual(len(self._contact_member_fk()), 1)
                restore()

    def test_init_skips_contact_member_fk_on_an_old_herd_table(self):
        """On a database without herd.contact_member_id (before 49 -> 50) init() adds nothing and does not fail."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        db.DATABASE.execute_sql("ALTER TABLE herd DROP COLUMN IF EXISTS contact_member_id")
        db.DATABASE.execute_sql("ALTER TABLE herd DROP COLUMN IF EXISTS contact_pending")
        rewind_migrations(50)

        db.init()

        self.assertNotIn("contact_member_id", {c.name for c in db.DATABASE.get_columns("herd")})
        # init() also created the yearly report's tables on this rewound database, which the boot guard reads as an
        # old report-branch database; a real boot migrates before init() (prestart, connect, verify)
        rewind_migrations(50)
        db.check_migrations()
        self.assertEqual(len(self._contact_member_fk()), 1)

    def test_herd_as_dict_has_no_internal_keys(self):
        gb = db.Genebank.create(name="Replay47c")
        herd = db.Herd.create(genebank=gb, herd="R47C", contact_pending=["email"])
        data = db.Herd.get_by_id(herd.id).as_dict()
        self.assertNotIn("contact_member", data)
        self.assertNotIn("contact_pending", data)
        self.assertEqual(db.Herd.get_by_id(herd.id).contact_pending, ["email"])

    def test_replay_32_to_33_adds_the_history_algorithm_version(self):
        """
        A database stamped at 32 gets genetics_history_state.algorithm_version,
        0 on an existing watermark, so the next reconcile recomputes.
        """
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        gb = db.Genebank.create(name="Replay33")
        rewind_migrations(33)
        db.DATABASE.execute_sql("ALTER TABLE genetics_history_state DROP COLUMN IF EXISTS algorithm_version")
        db.DATABASE.execute_sql(
            "INSERT INTO genetics_history_state (genebank_id, checked_at, version, definition_version)"
            " VALUES (%s, now(), 5, 2)",
            (gb.id,),
        )

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertIn("algorithm_version", {c.name for c in db.DATABASE.get_columns("genetics_history_state")})
        row = db.DATABASE.execute_sql(
            "SELECT algorithm_version FROM genetics_history_state WHERE genebank_id = %s", (gb.id,)
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_init_stamps_only_fresh_database(self):
        """
        init() must record the bootstrap version on a database it creates from
        nothing — SchemaHistory.version is a plain primary key, so the old
        save() silently degraded into a zero-row UPDATE and left the table
        empty. A second init() must leave that single row untouched.
        """
        self.addCleanup(db.check_migrations)

        if db.SchemaHistory.table_exists():
            db.SchemaHistory.drop_table()

        db.init()
        self.assertEqual(
            [(row.version, row.comment) for row in db.SchemaHistory.select()],
            [(db.CURRENT_SCHEMA_VERSION, "Bootstrapped")],
        )
        applied = db.SchemaHistory.get_by_id(db.CURRENT_SCHEMA_VERSION).applied

        db.init()
        self.assertEqual(
            [(row.version, row.comment) for row in db.SchemaHistory.select()],
            [(db.CURRENT_SCHEMA_VERSION, "Bootstrapped")],
        )
        self.assertEqual(db.SchemaHistory.get_by_id(db.CURRENT_SCHEMA_VERSION).applied, applied)

    def test_init_does_not_stamp_migrated_database(self):
        """
        init() may only stamp a fresh bootstrap. Stamping a database that is
        one version behind would push MAX(version) to CURRENT_SCHEMA_VERSION
        and make check_migrations() skip the migration it still owes.
        """
        self.addCleanup(db.check_migrations)
        previous_version = db.CURRENT_SCHEMA_VERSION - 1

        rewind_migrations(db.CURRENT_SCHEMA_VERSION)
        if db.SchemaHistory.get_or_none(db.SchemaHistory.version == previous_version) is None:
            db.SchemaHistory.insert(  # pylint: disable=E1120
                version=previous_version,
                comment="test seed",
                applied=datetime.now(),
            ).execute()

        db.init()
        self.assertEqual(
            self._max_schema_version(),
            previous_version,
            "init() stamped an existing database — check_migrations() would skip pending migrations",
        )

        # init() just created v50 tables on the old stamp. Restore the pre-migration shape before replay.
        rewind_migrations(db.CURRENT_SCHEMA_VERSION)
        db.check_migrations()
        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)

    def test_replay_40_to_41_creates_the_mail_queue(self):
        """A database stamped at 40 gets the three mail tables, with a fresh bootstrap's indexes, unaudited."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("index introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        tables = ("mail_attempt", "mail_message", "mail_sender")

        def indexes():
            return {(i.table, i.name, tuple(i.columns), i.unique) for t in tables for i in db.DATABASE.get_indexes(t)}

        fresh = indexes()
        rewind_migrations(41)
        db.DATABASE.execute_sql("DROP TABLE mail_attempt, mail_message, mail_sender")

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertEqual(indexes(), fresh)
        self.assertIn(("mail_message", "mailmessage_dedupe_key", ("dedupe_key",), True), fresh)
        self.assertIn(
            (
                "mail_message",
                "mailmessage_status_next_attempt_at_priority_id",
                ("status", "next_attempt_at", "priority", "id"),
                False,
            ),
            fresh,
        )
        self.assertTrue(set(tables).isdisjoint(db.AUDITED_TABLES))

    def test_replay_41_to_42_creates_the_intake_queue(self):
        """A database stamped at 41 gets the queue's tables with a fresh bootstrap's indexes, unaudited."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("index introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        tables = [m._meta.table_name for m in db.INBOX_MODELS]

        def indexes():
            return {(i.table, i.name, tuple(i.columns), i.unique) for t in tables for i in db.DATABASE.get_indexes(t)}

        fresh = indexes()
        rewind_migrations(42)
        db.DATABASE.execute_sql(f"DROP TABLE {', '.join(tables)} CASCADE")

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertEqual(indexes(), fresh)
        self.assertIn(("inbox_item", "inboxitem_gmail_message_id", ("gmail_message_id",), True), fresh)
        self.assertTrue(set(tables).isdisjoint(db.AUDITED_TABLES))

    def test_replay_42_to_43_lets_an_original_go_and_records_seller_and_buyer(self):
        """A database stamped at 42 gets a nullable original and the two member columns, as a fresh bootstrap."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)

        def shape():
            columns = {
                (t, c.name, c.null)
                for t in ("inbox_document", "inbox_item", "gmail_processed")
                for c in db.DATABASE.get_columns(t)
            }
            indexes = {(i.name, tuple(i.columns), i.unique) for i in db.DATABASE.get_indexes("inbox_document")}
            keys = {(k.column, k.dest_table, k.dest_column) for k in db.DATABASE.get_foreign_keys("inbox_document")}
            return columns, indexes, keys

        fresh = shape()
        rewind_migrations(43)
        if (
            db.SchemaHistory.get_or_none(db.SchemaHistory.version == 42) is None
        ):  # init() stamps only the latest version
            db.SchemaHistory.insert(version=42, comment="test seed", applied=datetime.now()).execute()  # pylint: disable=E1120
        db.DATABASE.execute_sql(
            "ALTER TABLE inbox_document DROP COLUMN seller_member_id, DROP COLUMN buyer_member_id, "
            "ALTER COLUMN original_path SET NOT NULL"
        )
        db.DATABASE.execute_sql("ALTER TABLE inbox_item DROP COLUMN sender_authenticated")
        db.DATABASE.execute_sql("ALTER TABLE gmail_processed DROP COLUMN failures")

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertEqual(shape(), fresh)
        self.assertIn(("inbox_document", "original_path", True), fresh[0])
        self.assertIn(("inbox_item", "sender_authenticated", True), fresh[0])
        self.assertIn(("gmail_processed", "failures", False), fresh[0])
        self.assertIn(("seller_member_id", "member", "member_id"), fresh[2])

    def _drop_rex_column(self):
        """The schema before 45 -> 46: no rex column, the audit trigger on, and the version row gone."""
        self.addCleanup(db.check_migrations)
        self.assertTrue(
            db.DATABASE.execute_sql(
                "SELECT 1 FROM pg_trigger WHERE tgrelid = 'individual'::regclass AND tgname = 'audit_trigger'"
            ).fetchone()
        )
        db.DATABASE.execute_sql("ALTER TABLE individual DROP COLUMN rex")
        rewind_migrations(self._migration_version('comment=f"individual.rex;'))

    def _individual_audit_rows(self):
        return db.AuditLog.select().where(db.AuditLog.table_name == "individual").count()

    def test_rex_kolumn(self):
        """A database stamped at 43 gets individual.rex, false for old rows, without audit rows, twice over."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self._drop_rex_column()
        names = lambda: {c.name for c in db.DATABASE.get_columns("individual")}  # noqa: E731
        self.assertNotIn("rex", names())
        rows = db.DATABASE.execute_sql("SELECT count(*) FROM individual").fetchone()[0]
        self.assertGreater(rows, 0)
        audit_before = self._individual_audit_rows()

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertIn("rex", names())
        self.assertEqual(
            db.DATABASE.execute_sql("SELECT count(*) FROM individual WHERE rex IS DISTINCT FROM false").fetchone()[0], 0
        )
        self.assertEqual(self._individual_audit_rows(), audit_before)  # the ALTER fires no row trigger
        rewind_migrations(46)
        db.check_migrations()  # a second run changes nothing and does not fail
        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        (default,) = db.DATABASE.execute_sql(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'individual' AND column_name = 'rex'"
        ).fetchone()
        self.assertEqual(default, "false")
        self.assertEqual(db.Individual.get_by_id(self.individuals[0].id).rex, False)

    def test_rex_ur_fritext(self):
        """Rex in a free-text note becomes rex = true; carriers, ej rex and the like do not. Text is untouched."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("regular expressions require PostgreSQL")
        yes = [
            ("rex", None),
            ("Rexpäls", None),
            ("rex-pälsad", None),
            ("ja, rexpälsad.", None),
            (None, "svart rex"),
            (None, "madagaskar-rex"),
            (None, "gul / svart japan, rexpälsad"),
            ("rexpälsad", "svart med vita inslag"),
            ("Rex", "bär blått"),
            ("Rex", "anlag för japan"),
        ]
        no = [
            ("nej", None),
            ("normal", None),
            ("-", None),
            (None, "bär rex"),
            (None, "rexbärare"),
            (None, "anlag för rex"),
            (None, "ej rex"),
            (None, "havanna med rexinslag"),
            ("icke-rex", None),
            ("inte en rex", None),
            ("utan rex", None),
            ("inget rex", None),
            ("Rex: nej", None),
            ("far rex", None),
            ("Rex", "bär rex"),
            ("Rexpäls: nej", None),
            ("Normalpäls, förälder är rex", None),
            ("Rex, bär blått", None),
            ("Rex, med vita inslag", None),
            ("Rex", "mor rex"),
            ("bär (rex)", None),
            ("Rex (nej)", None),
            ("Rex? nej", None),
            ("Rex \u2013 nej", None),
            ('ej "rex"', None),
            ("rex/japan-bärare", None),
            ("kanske rex", None),
            ("ev. rex", None),
            ("testad för rex, negativ", None),
            ("kullsyskon är rex", None),
            ("efter rexhane", None),
            ("rexmor", None),
            ("rexfri", None),
            ("REXBÄRARE", None),
            ("mamman är rex", None),
            ("Inga tecken på rex", None),
            ("rexliknande", None),
            ("rex", "Inga tecken på rex"),
            ("rex negativt", None),
            ("okänt om rex", None),
            ("mormor rex", None),
            ("rex eller normal", None),
            ("Rex: -", None),
            ("Rex: 0", None),
            ("rex-fri", None),
            ("fri från rex", None),
            ("rex oklart", None),
            ("har rexgen", None),
            ("rexkorsning", None),
            ("50% rex", None),
            ("kan vara rex", None),
            ("Normalt", "svart rex"),
            ("Normalpäls", "rex"),
            ("Rex", "mamma rex"),
            ("Saknar rex", None),
            ("Saknar rexpäls", None),
            ("farmor har rex", None),
            ("Eventuell rex", None),
            ("Möjlig rex", None),
            ("Trolig rex", None),
            ("Förmodligen rex", None),
            ("Verkar vara rex", None),
            ("Ser ut som rex", None),
            ("Ska testas för rex", None),
            ("Uppges vara rex", None),
            ("Vanlig eller rex", None),
            ("Paras med rex", None),
            ("Korsad med rex", None),
            ("Gotland x rex", None),
            ("1/2 rex", None),
            ("F1 rex", None),
            ("No rex", None),
            ("rex", "ickerex"),
            ("ba\u0308r rex", None),
            ("blandras rex", None),
            ("blandning rex", None),
            ("gravid rex", None),
            ("rexpälsliknande", None),
            ("rexpälsmor", None),
            ("ja, rexpälsgen", None),
            ("-rex", None),
            ("svart -rex", None),
            ("- rex", None),
            ("vit/-rex", None),
            ("nej", "svart rex"),
            ("inga avvikelser", "svart rex"),
            ("ickerex", None),
        ]
        ids = {}
        for i, (hair, color_note) in enumerate(yes + no):
            ids[(hair, color_note)] = db.Individual.create(
                origin_herd=self.herds[0], number=f"G1-77{i:02d}", hair_notes=hair, color_note=color_note
            ).id
        noted = db.Individual.create(
            origin_herd=self.herds[0], number="G1-7600", hair_notes="rex", notes="normalpäls, rex var felskrivet"
        ).id
        self._drop_rex_column()

        with self.assertLogs("herdbook.db", level="INFO") as logged:
            db.check_migrations()

        self.assertFalse(self._rex(noted))
        for key in yes:
            self.assertTrue(self._rex(ids[key]), key)
        for key in no:
            self.assertFalse(self._rex(ids[key]), key)
        for (hair, color_note), individual_id in ids.items():
            row = db.DATABASE.execute_sql(
                "SELECT hair_notes, color_note FROM individual WHERE individual_id = %s", (individual_id,)
            ).fetchone()
            self.assertEqual(row, (hair, color_note))
        excluded = 1 + sum(1 for h, c in no if "rex" in f"{h}{c}".lower())  # +1: the notes rabbit
        self.assertIn(f"rex: set from free text on {len(yes)}, {excluded} excluded", "\n".join(logged.output))

    def test_rex_replay_keeps_corrections(self):
        """A replay of 43 -> 44 on a database that already has the column does not set rex again or log rows."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("regular expressions require PostgreSQL")
        rabbit = db.Individual.create(origin_herd=self.herds[0], number="G1-7790", hair_notes="rex")
        self._drop_rex_column()
        db.check_migrations()
        self.assertTrue(self._rex(rabbit.id))
        db.DATABASE.execute_sql("UPDATE individual SET rex = false WHERE individual_id = %s", (rabbit.id,))
        audit_before = self._individual_audit_rows()
        rewind_migrations(self._migration_version('comment=f"individual.rex;'))
        db.check_migrations()
        self.assertFalse(self._rex(rabbit.id))
        self.assertEqual(self._individual_audit_rows(), audit_before)

    def _rex(self, individual_id):
        return db.DATABASE.execute_sql(
            "SELECT rex FROM individual WHERE individual_id = %s", (individual_id,)
        ).fetchone()[0]

    def test_replay_47_to_48_makes_a_google_identity_unique(self):
        """A database stamped at 47 gets the fresh bootstrap's index; one where two accounts hold an identity stays at
        47 without it, and the next start after the extra one is unlinked migrates."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("index introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)

        def index():
            return [(i.columns, i.unique) for i in db.DATABASE.get_indexes("authenticators") if "google" in i.name]

        fresh = index()
        self.assertEqual(fresh, [(["auth_data"], True)])
        first, second = da.register_user("ett@example.org", None), da.register_user("tva@example.org", None)
        db.Authenticators.create(user=first.id, auth="google", auth_data="sub-delad")
        with self.assertRaises(peewee.IntegrityError), db.DATABASE.atomic():
            db.Authenticators.create(user=second.id, auth="google", auth_data="sub-delad")
        db.Authenticators.create(user=second.id, auth="password", auth_data="sub-delad")  # other methods may repeat

        rewind_migrations(48)
        db.DATABASE.execute_sql('DROP INDEX "idx_authenticators_google"')
        duplicate = db.Authenticators.create(user=second.id, auth="google", auth_data="sub-delad")
        self.addCleanup(duplicate.delete_instance)  # runs before check_migrations if an assert below fails

        with self.assertRaises(peewee.IntegrityError):
            db.check_migrations()
        self.assertEqual(self._max_schema_version(), 47)
        self.assertEqual(index(), [])

        duplicate.delete_instance()
        db.check_migrations()
        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertEqual(index(), fresh)

    def test_replay_48_to_49_creates_login_codes_and_previous_addresses(self):
        """A database stamped at 48 gets the two tables and the member column as a fresh bootstrap has them, with
        their indexes and foreign keys, unaudited."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        tables = ("login_code", "member_previous_address")

        def shape():
            columns = {
                (t, c.name, c.data_type, c.null) for t in ("member", *tables) for c in db.DATABASE.get_columns(t)
            }
            indexes = {(t, i.name, tuple(i.columns), i.unique) for t in tables for i in db.DATABASE.get_indexes(t)}
            keys = {(t, k.column, k.dest_table) for t in tables for k in db.DATABASE.get_foreign_keys(t)}
            return columns, indexes, keys

        fresh = shape()
        rewind_migrations(49)
        db.DATABASE.execute_sql("DROP TABLE login_code, member_previous_address")
        db.DATABASE.execute_sql("ALTER TABLE member DROP COLUMN email_login_from")

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertEqual(shape(), fresh)
        self.assertIn(("member", "email_login_from", "timestamp with time zone", True), fresh[0])
        self.assertIn(("login_code", "logincode_browser_hash", ("browser_hash",), False), fresh[1])
        self.assertIn(("member_previous_address", "member_id", "member"), fresh[2])
        self.assertTrue(set(tables).isdisjoint(db.AUDITED_TABLES))

    def test_replay_adds_account_rules_acceptance(self):
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)

        table = "account_rules_snapshot"

        def shape():
            columns = {
                (t, c.name, c.data_type, c.null)
                for t in ("hbuser", table)
                for c in db.DATABASE.get_columns(t)
                if t == table or c.name.startswith("rules_")
            }
            keys = {(k.column, k.dest_table, k.dest_column) for k in db.DATABASE.get_foreign_keys("hbuser")}
            rules = db.DATABASE.execute_sql("SELECT rulename FROM pg_rules WHERE tablename = %s", (table,))
            return columns, keys, db.DATABASE.get_primary_keys(table), {name for (name,) in rules}

        fresh = shape()
        version = self._migration_version("hbuser account rules acceptance")
        rewind_migrations(version)
        db.DATABASE.execute_sql(
            "ALTER TABLE hbuser DROP COLUMN rules_accepted_at, DROP COLUMN rules_version, DROP COLUMN rules_sha256"
        )
        db.DATABASE.execute_sql("DROP TABLE account_rules_snapshot")
        db.check_migrations()
        self.assertEqual(db.SchemaHistory.get_by_id(version).comment, "hbuser account rules acceptance")
        self.assertEqual(shape(), fresh)
        columns, keys, pk, rules = fresh
        self.assertEqual(
            columns,
            {
                ("hbuser", "rules_accepted_at", "timestamp with time zone", True),
                ("hbuser", "rules_version", "text", True),
                ("hbuser", "rules_sha256", "text", True),
                (table, "sha256", "text", False),
                (table, "text", "text", False),
                (table, "cms_version", "text", False),
                (table, "first_accepted_at", "timestamp with time zone", False),
            },
        )
        self.assertIn(("rules_sha256", table, "sha256"), keys)
        self.assertEqual(pk, ["sha256"])
        self.assertEqual(rules, {"account_rules_no_update", "account_rules_no_delete"})
        self.assertNotIn(table, db.AUDITED_TABLES)
        user = db.User.get_by_id(self.viewer.id)
        self.assertEqual((user.rules_accepted_at, user.rules_version, user.rules_sha256), (None, None, None))

    def test_replay_adds_name_on_check_page(self):
        """Stamboken #6: an older database gets the person's choice, on for the accounts it has, and the issuing
        role, shaped as a fresh bootstrap."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)

        def column():
            return {
                (t, c.name, c.null, c.default)
                for t in ("hbuser", "digitalcertificatev2")
                for c in db.DATABASE.get_columns(t)
                if c.name in ("name_on_check_page", "issued_as")
            }

        fresh = column()
        version = self._migration_version("name_on_check_page")
        rewind_migrations(version)
        db.DATABASE.execute_sql("ALTER TABLE hbuser DROP COLUMN name_on_check_page")
        # the hbuser trigger as at version 46, so the test sees the migration re-attach it
        db.DATABASE.execute_sql(
            "CREATE OR REPLACE TRIGGER audit_trigger AFTER INSERT OR UPDATE OR DELETE ON hbuser"
            " FOR EACH ROW EXECUTE FUNCTION audit_trigger_func('password_hash', 'last_active', 'user_id')"
        )
        db.DATABASE.execute_sql("ALTER TABLE digitalcertificatev2 DROP COLUMN issued_as")
        # an account whose person was anonymised before the migration
        membership = db.Membership.create(member_number=4711)
        db.MatrikelAudit.create(
            action="person_user_unlinked",
            membership=membership,
            payload={"person_id": 1, "user_id": self.viewer.id, "source": "anonymize"},
        )
        audit_before = db.AuditLog.select().where(db.AuditLog.table_name == "hbuser").count()

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertEqual(column(), fresh)
        # Accounts that existed keep showing their name until they change it (Jonas 2026-11-23), without audit rows
        self.assertTrue(db.User.get_by_id(self.owner.id).name_on_check_page)
        self.assertFalse(db.User.get_by_id(self.viewer.id).name_on_check_page)  # anonymised before: off
        self.assertEqual(db.AuditLog.select().where(db.AuditLog.table_name == "hbuser").count(), audit_before)
        # A new account has not chosen yet
        self.assertIsNone(db.User.get_by_id(da.register_user("ny", "pass").id).name_on_check_page)

    def test_replay_lets_a_notice_point_at_a_rabbit(self):
        """An older database gets notice.individual_id, as a fresh bootstrap."""
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)

        def shape():
            columns = {(c.name, c.null) for c in db.DATABASE.get_columns("notice")}
            keys = {(k.column, k.dest_table, k.dest_column) for k in db.DATABASE.get_foreign_keys("notice")}
            indexes = {(i.name, tuple(i.columns), i.unique) for i in db.DATABASE.get_indexes("notice")}
            buyer_columns = {(c.name, c.null) for c in db.DATABASE.get_columns("buyer_contact")}
            return columns, keys, indexes, buyer_columns

        fresh = shape()
        version = self._migration_version("notice.individual")
        db.SchemaHistory.delete().where(db.SchemaHistory.version >= version).execute()
        if db.SchemaHistory.get_or_none(db.SchemaHistory.version == version - 1) is None:
            db.SchemaHistory.insert(  # pylint: disable=E1120
                version=version - 1, comment="test seed", applied=datetime.now()
            ).execute()
        db.DATABASE.execute_sql("ALTER TABLE notice DROP COLUMN individual_id")
        db.DATABASE.execute_sql(
            "ALTER TABLE buyer_contact DROP COLUMN erased_email_hash, DROP COLUMN email_review_pending"
        )

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        self.assertEqual(shape(), fresh)
        self.assertIn(("individual_id", True), fresh[0])
        self.assertIn(("individual_id", "individual", "individual_id"), fresh[1])
        self.assertIn(("notice_individual_id", ("individual_id",), False), fresh[2])
        self.assertIn(("erased_email_hash", True), fresh[3])
        self.assertIn(("email_review_pending", False), fresh[3])

    @staticmethod
    def _migration_version(marker):
        """The version the migration whose source names `marker` stamps: survives renumbering and later migrations."""
        return next(to for (_, to), fn in db.MIGRATIONS.items() if marker in inspect.getsource(fn))

    def _max_schema_version(self):
        return db.SchemaHistory.select(  # pylint: disable=E1120
            db.fn.MAX(db.SchemaHistory.version)
        ).scalar()

    def _migration_lock_count(self, granted):
        (count,) = db.DATABASE.execute_sql(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = %s AND granted = %s",
            (db.MIGRATION_LOCK_KEY, granted),
        ).fetchone()
        return count

    def _wait_for_migration_lock_waiter(self, timeout=30):
        """Poll pg_locks until a session is queued on the migration lock."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._migration_lock_count(granted=False):
                return True
            time.sleep(0.05)
        return False

    def test_concurrent_replay(self):
        """
        Replays the last migration from several threads at once, like gunicorn
        workers importing the app concurrently. The advisory lock in
        check_migrations() must serialize them so that no thread errors and
        the replay is applied exactly once.
        """
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("advisory-lock serialization requires PostgreSQL")

        rewind_migrations(db.CURRENT_SCHEMA_VERSION)
        # Restore the schema version even if this test fails midway —
        # schemahistory is not truncated between tests.
        self.addCleanup(db.check_migrations)

        workers = 4
        barrier = threading.Barrier(workers, timeout=30)
        errors = []

        def replay():
            try:
                barrier.wait()
                db.check_migrations()
            except Exception as exception:  # pylint: disable=broad-except
                errors.append(exception)
            finally:
                if not db.DATABASE.is_closed():
                    db.DATABASE.close()

        threads = [threading.Thread(target=replay) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)

    def test_replay_waits_for_migration_lock(self):
        """
        check_migrations() must block on the migration advisory lock and
        re-read the schema version once it acquires it, so that late workers
        become no-ops instead of replaying migrations a second time.
        """
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("advisory locks require PostgreSQL")

        lock_sql = "SELECT pg_advisory_lock(%s, hashtext(current_database()))"
        unlock_sql = "SELECT pg_advisory_unlock(%s, hashtext(current_database()))"

        rewind_migrations(db.CURRENT_SCHEMA_VERSION)
        # Restore the schema version even if this test fails midway —
        # schemahistory is not truncated between tests.
        self.addCleanup(db.check_migrations)
        rolled_back_version = self._max_schema_version()

        errors = []

        def replay():
            try:
                db.check_migrations()
            except Exception as exception:  # pylint: disable=broad-except
                errors.append(exception)
            finally:
                if not db.DATABASE.is_closed():
                    db.DATABASE.close()

        # Hold the migration lock from the main thread's session while a
        # "worker" tries to replay.
        db.DATABASE.execute_sql(lock_sql, (db.MIGRATION_LOCK_KEY,))
        thread = threading.Thread(target=replay)
        try:
            thread.start()
            # Deterministic: wait until the worker is actually queued on the
            # advisory lock before asserting that nothing has been replayed.
            self.assertTrue(
                self._wait_for_migration_lock_waiter(),
                "check_migrations() should queue on the migration lock",
            )
            self.assertEqual(self._max_schema_version(), rolled_back_version)
        finally:
            db.DATABASE.execute_sql(unlock_sql, (db.MIGRATION_LOCK_KEY,))
            thread.join(timeout=120)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        # Neither the worker nor this test may leave the migration lock held.
        self.assertEqual(self._migration_lock_count(granted=True), 0)

    def test_migration_replays(self):
        """
        Run migrations sereral times to verify that all migrations work even
        if they have been applied already.
        """
        db.check_migrations()

        for _ in range(2):
            rewind_migrations(1)
            db.SchemaHistory.drop_table()
            db.check_migrations()

        self.assertTrue(db.SchemaHistory.table_exists())
        self.assertEqual(
            db.SchemaHistory()
            .select(db.fn.MAX(db.SchemaHistory.version))  # pylint: disable=E1120
            .scalar(),
            db.CURRENT_SCHEMA_VERSION,
        )


# jscpd:ignore-end
