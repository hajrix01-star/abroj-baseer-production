import base64
import unittest

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


class TrialFixtures:
    private = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_rules = cls.env["ir.rule"].browse([
            cls.env.ref("baseer_dms_trial." + suffix).id
            for suffix in ("private_storage", "private_directory", "private_file", "private_group", "private_share")
        ])
        cls.private_rules.write({"active": cls.private})
        cls.company_a = cls.env["res.company"].create({"name": "DMS synthetic A"})
        cls.company_b = cls.env["res.company"].create({"name": "DMS synthetic B"})
        cls.editor = new_test_user(
            cls.env, login="dms-trial-editor", password="trial", groups="dms.group_dms_user",
            company_id=cls.company_a.id, company_ids=[(6, 0, [cls.company_a.id])],
        )
        cls.reader = new_test_user(
            cls.env, login="dms-trial-reader", groups="dms.group_dms_user",
            company_id=cls.company_a.id, company_ids=[(6, 0, [cls.company_a.id])],
        )
        cls.outsider = new_test_user(
            cls.env, login="dms-trial-outsider", groups="dms.group_dms_user",
            company_id=cls.company_a.id, company_ids=[(6, 0, [cls.company_a.id])],
        )
        # Same editor group on both companies makes the company rule, not just
        # missing group membership, responsible for cross-company denial.
        editor_group = cls.env["dms.access.group"].create({
            "name": "Trial editors", "perm_create": True, "perm_write": True,
            "perm_unlink": True, "explicit_user_ids": [(6, 0, cls.editor.ids)],
        })
        reader_group = cls.env["dms.access.group"].create({
            "name": "Trial readers", "perm_create": False, "perm_write": False,
            "perm_unlink": False, "explicit_user_ids": [(6, 0, cls.reader.ids)],
        })
        cls.directories = []
        cls.files = []
        cls.payload = base64.b64encode(b"Synthetic contract/license only; no real data.")
        for company in (cls.company_a, cls.company_b):
            storage = cls.env["dms.storage"].create({
                "name": "Trial " + company.name, "company_id": company.id,
                "save_type": "file", "model_ids": [(5, 0, 0)],
                "include_message_attachments": False,
                "inherit_access_from_parent_record": False,
            })
            directory = cls.env["dms.directory"].create({
                "name": "Contracts and licenses", "storage_id": storage.id,
                "is_root_directory": True,
                "group_ids": [(6, 0, (editor_group | reader_group).ids)],
            })
            cls.directories.append(directory)
            cls.files.append(cls.env["dms.file"].create({
                "name": "synthetic-contract.txt", "directory_id": directory.id,
                "content": cls.payload,
            }))
        cls.dir_a, cls.dir_b = cls.directories
        cls.file_a, cls.file_b = cls.files

    def as_user(self, record, user=None):
        return record.with_user(user or self.editor).with_context(
            allowed_company_ids=[self.company_a.id]
        )


@tagged("post_install", "-at_install", "baseer_dms_trial")
class TestDmsTrial(TrialFixtures, TransactionCase):
    def test_company_search_and_direct_read(self):
        for record in (self.dir_b.storage_id, self.dir_b, self.file_b):
            model = self.as_user(self.env[record._name])
            self.assertFalse(model.search([("id", "=", record.id)]))
            with self.assertRaises(AccessError):
                self.as_user(record).read(["name"])
        self.assertEqual(self.as_user(self.file_a).content, self.payload)
        with self.assertRaises(AccessError):
            self.as_user(self.file_b).read(["content"])

    def test_cross_company_mutations_denied(self):
        foreign = self.as_user(self.file_b)
        with self.assertRaises(AccessError):
            foreign.write({"name": "forbidden.txt"})
        with self.assertRaises(AccessError):
            foreign.unlink()
        with self.assertRaises(AccessError):
            self.as_user(self.env["dms.file"]).create({
                "name": "forbidden.txt", "directory_id": self.dir_b.id,
                "content": self.payload,
            })

    @unittest.expectedFailure
    def test_native_cross_company_move_known_defect(self):
        # Strict assertion retained: native write validates old record only.
        # The private QA guard does not claim to repair this native defect.
        with self.assertRaises(AccessError):
            self.as_user(self.file_a).write({"directory_id": self.dir_b.id})

    def test_reader_and_no_group_access(self):
        self.assertEqual(self.as_user(self.file_a, self.reader).content, self.payload)
        with self.assertRaises(AccessError):
            self.as_user(self.file_a, self.reader).write({"name": "reader.txt"})
        with self.assertRaises(AccessError):
            self.as_user(self.file_a, self.reader).unlink()
        with self.assertRaises(AccessError):
            self.as_user(self.env["dms.file"], self.reader).create({
                "name": "reader-create.txt", "directory_id": self.dir_a.id,
                "content": self.payload,
            })
        self.assertFalse(self.as_user(self.env["dms.file"], self.outsider).search([
            ("id", "=", self.file_a.id)
        ]))
        with self.assertRaises(AccessError):
            self.as_user(self.file_a, self.outsider).read(["content"])

    def test_own_company_editor_crud(self):
        created = self.as_user(self.env["dms.file"]).create({
            "name": "editor-create.txt", "directory_id": self.dir_a.id,
            "content": self.payload,
        })
        created.write({"name": "editor-renamed.txt"})
        self.assertEqual(created.name, "editor-renamed.txt")
        self.assertEqual(created.company_id, self.company_a)
        created.unlink()
        self.assertFalse(created.exists())

    def test_duplicates_native_limits_and_physical_storage(self):
        model = self.as_user(self.env["dms.file"])
        with self.assertRaises(ValidationError):
            model.create({"name": self.file_a.name, "directory_id": self.dir_a.id,
                          "content": self.payload})
        duplicate = model.create({
            "name": "same-bytes-different-name.txt", "directory_id": self.dir_a.id,
            "content": self.payload,
        })
        self.assertNotEqual(duplicate.id, self.file_a.id)
        self.assertEqual(duplicate.checksum, self.file_a.checksum)
        # Logical duplicates are allowed. Filestore dedup is separate evidence.
        attachments = self.env["ir.attachment"].search([
            ("res_model", "=", "dms.file"), ("res_field", "=", "content_file"),
            ("res_id", "in", [duplicate.id, self.file_a.id]),
        ])
        self.assertEqual(len(attachments), 2)
        self.assertTrue(all(attachments.mapped("store_fname")))
        self.assertEqual(len(set(attachments.mapped("store_fname"))), 1)
        self.assertFalse(duplicate.attachment_id)
        self.assertFalse(self.dir_a.storage_id.model_ids)
        self.assertFalse(self.dir_a.storage_id.include_message_attachments)

    def test_no_tokens_and_portal_public_denial(self):
        self.assertFalse(self.file_a.access_token)
        self.assertFalse(self.dir_a.access_token)

        self.assertFalse(self.file_a.check_access_token("invalid-trial-token"))
        for user in (self.env.ref("base.public_user"), new_test_user(
            self.env, login="dms-trial-portal", groups="base.group_portal",
        )):
            with self.assertRaises(AccessError):
                self.file_a.with_user(user).read(["content"])


@tagged("post_install", "-at_install", "baseer_dms_trial")
class TestDmsTrialDownload(TrialFixtures, HttpCase):
    def test_guessed_id_download_does_not_expose_bytes(self):
        path = f"/my/dms/file/{self.file_a.id}/download"
        for suffix in ("", "?access_token=invalid-trial-token"):
            response = self.url_open(path + suffix)
            self.assertNotIn(base64.b64decode(self.payload), response.content)
            self.assertNotIn("attachment;", response.headers.get("Content-Disposition", ""))
        self.authenticate("dms-trial-editor", "trial")
        own = self.url_open(path)
        self.assertEqual(own.content, base64.b64decode(self.payload))
        foreign = self.url_open(f"/my/dms/file/{self.file_b.id}/download")
        self.assertNotIn(base64.b64decode(self.payload), foreign.content)


class PrivateFixtures(TrialFixtures):
    private = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = cls.env.ref("base.user_admin")
        cls.owner.write({"company_ids": [(4, cls.company_a.id), (4, cls.company_b.id)]})
        cls.manager = new_test_user(
            cls.env, login="dms-private-manager", password="trial",
            groups="dms.group_dms_manager", company_id=cls.company_a.id,
            company_ids=[(6, 0, [cls.company_a.id, cls.company_b.id])],
        )
        cls.dir_a.group_ids.write({"explicit_user_ids": [(4, cls.owner.id), (4, cls.manager.id)]})
        cls.attachment = cls.env["ir.attachment"].search([
            ("res_model", "=", "dms.file"), ("res_id", "=", cls.file_a.id),
            ("res_field", "=", "content_file"),
        ])


@tagged("post_install", "-at_install", "baseer_dms_trial")
class TestDmsPrivate(PrivateFixtures, TransactionCase):
    def test_manager_share_wizard_denied_before_token(self):
        with self.assertRaises(AccessError):
            self.env["wizard.dms.share"].with_user(self.manager).with_context(
                active_model="dms.file", active_id=self.file_a.id,
            ).create({"res_model": "dms.file", "res_id": self.file_a.id})
        self.assertFalse(self.file_a.access_token)
        self.assertFalse(self.dir_a.access_token)

    def test_owner_access_and_manager_denied(self):
        owner_file = self.as_user(self.file_a, self.owner)
        self.assertFalse(owner_file.env.su)
        self.assertEqual(owner_file.content, self.payload)
        owner_file.write({"name": "owner-edited.txt"})
        for record in (self.dir_a.storage_id, self.dir_a, self.file_a, self.dir_a.group_ids):
            forbidden = self.as_user(record, self.manager)
            self.assertFalse(self.as_user(self.env[record._name], self.manager).search([
                ("id", "in", record.ids)
            ]))
            with self.assertRaises(AccessError):
                forbidden.read(["name"])
            with self.assertRaises(AccessError):
                forbidden.write({"name": "manager-forbidden"})
            with self.assertRaises(AccessError):
                forbidden.unlink()
        with self.assertRaises(AccessError):
            self.as_user(self.env["dms.file"], self.manager).create({
                "name": "denied.txt", "directory_id": self.dir_a.id, "content": self.payload,
            })

    def test_attachment_and_token_write_denied(self):
        self.assertEqual(len(self.attachment), 1)
        for user in (self.manager, self.env.ref("base.public_user")):
            with self.assertRaises(AccessError):
                self.attachment.with_user(user).read(["datas"])
            with self.assertRaises(AccessError):
                self.attachment.with_user(user).write({"name": "denied.txt"})
            with self.assertRaises(AccessError):
                self.env["ir.attachment"].with_user(user).create({
                    "name": "denied.txt", "res_model": "dms.file",
                    "res_id": self.file_a.id, "datas": self.payload,
                })
            with self.assertRaises(AccessError):
                self.file_a.with_user(user).write({"access_token": "invalid-trial-token"})
        self.assertFalse(self.file_a.access_token)
        self.assertFalse(self.dir_a.access_token)


@tagged("post_install", "-at_install", "baseer_dms_trial")
class TestDmsPrivateDownload(PrivateFixtures, HttpCase):
    def test_private_download_denied_even_for_manager(self):
        path = f"/my/dms/file/{self.file_a.id}/download"
        for login in (None, "dms-private-manager"):
            if login:
                self.authenticate(login, "trial")
            for suffix in ("", "?access_token=invalid-trial-token"):
                response = self.url_open(path + suffix)
                self.assertNotIn(base64.b64decode(self.payload), response.content)
        self.assertFalse(self.file_a.access_token)
