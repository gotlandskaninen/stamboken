#!/usr/bin/env python3
"""
Unit tests for the herdbook endpoints.

isort:skip_file
"""
# Fairly lax pylint settings as we want to test a lot of things

# pylint: disable=too-many-public-methods
# pylint: disable=too-many-statements

import threading
import time
from datetime import datetime

import peewee

import utils.data_access as da

# pylint: disable=import-error
import utils.database as db

# pylint: disable=import-error
from tests.database_test import DatabaseTest
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

        self.assertDictEqual(h0_result, h0_expected)
        self.assertDictEqual(h1_result, h1_expected)

        # manager
        h0_result = self.herds[0].filtered_dict(self.manager)
        h1_result = self.herds[1].filtered_dict(self.manager)
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
        if db.SchemaHistory.table_exists():
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

        db.SchemaHistory.delete().where(db.SchemaHistory.version == db.CURRENT_SCHEMA_VERSION).execute()

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

        db.SchemaHistory.delete().where(db.SchemaHistory.version >= 31).execute()
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

        db.SchemaHistory.delete().where(db.SchemaHistory.version >= 32).execute()
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
        db.SchemaHistory.delete().where(db.SchemaHistory.version >= 34).execute()
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
        db.SchemaHistory.delete().where(db.SchemaHistory.version >= 36).execute()
        db.DATABASE.execute_sql("ALTER TABLE individual DROP COLUMN IF EXISTS microchip")

        db.check_migrations()

        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)
        ind = self.individuals[0]
        for chip in ("752098100012345", None):
            db.Individual.update(microchip=chip).where(db.Individual.id == ind.id).execute()
            self.assertEqual(db.Individual.get_by_id(ind.id).microchip, chip)
        for chip in ("", "75209810001234", "7520981000123456", "75209810001234x"):
            with self.subTest(chip=chip), self.assertRaises((peewee.IntegrityError, peewee.DataError)), db.DATABASE.atomic():
                db.Individual.update(microchip=chip).where(db.Individual.id == ind.id).execute()

    def test_replay_32_to_33_adds_the_history_algorithm_version(self):
        """
        A database stamped at 32 gets genetics_history_state.algorithm_version,
        0 on an existing watermark, so the next reconcile recomputes.
        """
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("column introspection requires PostgreSQL")
        self.addCleanup(db.check_migrations)
        gb = db.Genebank.create(name="Replay33")
        db.SchemaHistory.delete().where(db.SchemaHistory.version >= 33).execute()
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

        db.SchemaHistory.delete().where(db.SchemaHistory.version >= db.CURRENT_SCHEMA_VERSION).execute()
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

        # The pending migration must still replay.
        db.check_migrations()
        self.assertEqual(self._max_schema_version(), db.CURRENT_SCHEMA_VERSION)

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

        db.SchemaHistory.delete().where(db.SchemaHistory.version == db.CURRENT_SCHEMA_VERSION).execute()
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

        db.SchemaHistory.delete().where(db.SchemaHistory.version == db.CURRENT_SCHEMA_VERSION).execute()
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

        if db.SchemaHistory.table_exists():
            db.SchemaHistory.drop_table()

        db.check_migrations()

        if db.SchemaHistory.table_exists():
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
