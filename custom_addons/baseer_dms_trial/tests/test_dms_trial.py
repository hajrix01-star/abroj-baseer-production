import base64
import json

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


class TrialFixtures:
    private = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_rules = cls.env["ir.rule"].browse([
            cls.env.ref("baseer_dms_trial." + suffix).id
            for suffix in ("private_storage", "private_directory", "private_file", "private_group", "private_share", "private_attachment")
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


@tagged("post_install", "-at_install", "baseer_dms_trial", "dms_known_defect")
class TestDmsKnownMoveDefect(TrialFixtures, TransactionCase):
    def test_native_cross_company_move_known_defect(self):
        # Strict reproducer remains an active acceptance gate for the fix.
        with self.assertRaises(AccessError):
            self.as_user(self.file_a).write({"directory_id": self.dir_b.id})


class DestinationFixtures(TrialFixtures):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.editor_groups = cls.dir_a.group_ids.filtered(lambda group: group.name == 'Trial editors')
        cls.readonly_group = cls.env['dms.access.group'].create({
            'name': 'Destination read and edit without create', 'perm_create': False,
            'perm_write': True, 'perm_unlink': False,
            'explicit_user_ids': [(6, 0, cls.editor.ids)],
        })
        cls.other_group = cls.env['dms.access.group'].create({
            'name': 'Destination unrelated group', 'perm_create': True,
            'perm_write': True, 'perm_unlink': True,
            'explicit_user_ids': [(6, 0, cls.outsider.ids)],
        })
        cls.create_only_group = cls.env['dms.access.group'].create({
            'name': 'Destination create without write', 'perm_create': True,
            'perm_write': False, 'perm_unlink': False,
            'explicit_user_ids': [(6, 0, cls.editor.ids)],
        })
        def root(name, group):
            return cls.env['dms.directory'].create({
                'name': name, 'storage_id': cls.dir_a.storage_id.id,
                'is_root_directory': True, 'inherit_group_ids': False,
                'group_ids': [(6, 0, group.ids)],
            })
        cls.readonly_root = root('Read-only destination root', cls.readonly_group)
        cls.other_root = root('Unrelated destination root', cls.other_group)
        cls.create_only_root = root('Create-only destination root', cls.create_only_group)
        def child(name, parent, group):
            return cls.env['dms.directory'].create({
                'name': name, 'parent_id': parent.id, 'inherit_group_ids': False,
                'group_ids': [(6, 0, group.ids)],
            })
        cls.readonly_child = child('Read-only child of writable parent', cls.dir_a, cls.readonly_group)
        cls.writable_child = child('Writable child of read-only parent', cls.readonly_root, cls.editor_groups)
        cls.movable_child = child('Movable source directory', cls.dir_a, cls.editor_groups)

    def allow_both_companies(self, record):
        self.editor.company_ids |= self.company_b
        return record.with_user(self.editor).with_context(
            allowed_company_ids=(self.company_a | self.company_b).ids,
        )

    def file_identity(self, record):
        record.invalidate_recordset()
        return (record.id, record.name, record.directory_id.id, record.company_id.id,
                record.checksum, record.content)


@tagged('post_install', '-at_install', 'baseer_dms_trial')
class TestDmsDestinationAccess(DestinationFixtures, TransactionCase):
    def test_cross_company_move_allowed_only_with_both_companies_and_groups(self):
        original_id, original_checksum = self.file_a.id, self.file_a.checksum
        blobs = self.env['ir.attachment'].search([
            ('res_model', '=', 'dms.file'), ('res_field', '=', 'content_file'),
            ('res_id', '=', original_id),
        ])
        original_blob_ids = blobs.ids
        self.allow_both_companies(self.file_a).write({
            'name': 'authorized-moved.txt', 'directory_id': self.dir_b.id,
        })
        self.file_a.invalidate_recordset()
        self.assertEqual(self.file_a.id, original_id)
        self.assertEqual(self.file_a.company_id, self.company_b)
        self.assertEqual(self.file_a.directory_id, self.dir_b)
        self.assertEqual(self.file_a.checksum, original_checksum)
        self.assertEqual(self.file_a.content, self.payload)
        self.assertEqual(self.env['ir.attachment'].search([
            ('res_model', '=', 'dms.file'), ('res_field', '=', 'content_file'),
            ('res_id', '=', original_id),
        ]).ids, original_blob_ids)

    def test_foreign_missing_group_readonly_and_false_file_destinations_denied(self):
        original = self.file_identity(self.file_a)
        for destination in (self.dir_b, self.other_root, self.readonly_root, self.readonly_child):
            with self.assertRaises(AccessError), self.cr.savepoint():
                self.as_user(self.file_a).write({'directory_id': destination.id})
            self.assertEqual(self.file_identity(self.file_a), original)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.as_user(self.file_a).write({'directory_id': False})
        self.assertEqual(self.file_identity(self.file_a), original)
        nonexistent_id = self.env['dms.directory'].search([], order='id desc', limit=1).id + 1000
        with self.assertRaises(AccessError):
            self.as_user(self.file_a).write({'directory_id': nonexistent_id})
        self.assertEqual(self.file_identity(self.file_a), original)

    def test_child_destination_own_create_is_used_instead_of_parent_create(self):
        # Target child grants create even though its parent grants only read/write.
        self.assertFalse(self.as_user(self.readonly_root).permission_create)
        self.as_user(self.file_a).write({'directory_id': self.writable_child.id})
        self.assertEqual(self.file_a.directory_id, self.writable_child)
        self.assertEqual(self.file_a.content, self.payload)
        self.as_user(self.movable_child).write({'parent_id': self.writable_child.id})
        self.assertEqual(self.movable_child.parent_id, self.writable_child)
        self.assertEqual(self.movable_child.company_id, self.company_a)

    def test_directory_parent_and_root_storage_destination_checks_precede_native_limits(self):
        original_parent = self.movable_child.parent_id
        original_storage = self.dir_a.storage_id
        for destination in (self.dir_b, self.other_root, self.readonly_root, self.readonly_child):
            with self.assertRaises(AccessError), self.cr.savepoint():
                self.as_user(self.movable_child).write({'parent_id': destination.id})
            self.assertEqual(self.movable_child.parent_id, original_parent)
            self.assertEqual(self.movable_child.company_id, self.company_a)
        with self.assertRaises((AccessError, UserError)), self.cr.savepoint():
            self.as_user(self.dir_a).write({'storage_id': self.dir_b.storage_id.id})
        self.assertEqual(self.dir_a.storage_id, original_storage)
        self.as_user(self.dir_a).write({'parent_id': False})
        self.assertFalse(self.dir_a.parent_id)
        self.assertEqual(self.dir_a.storage_id, original_storage)
        # Authorization does not remove native cross-storage directory limits.
        with self.assertRaises(UserError), self.cr.savepoint():
            self.allow_both_companies(self.movable_child).write({'parent_id': self.dir_b.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            self.allow_both_companies(self.dir_a).write({'storage_id': self.dir_b.storage_id.id})
        self.assertEqual(self.movable_child.parent_id, original_parent)
        self.assertEqual(self.dir_a.storage_id, original_storage)

    def test_batch_source_and_destination_denial_roll_back_all_files(self):
        second = self.env['dms.file'].create({
            'name': 'second-source.txt', 'directory_id': self.dir_a.id, 'content': self.payload,
        })
        for batch, destination in ((self.file_a | second, self.readonly_child),
                                   (self.file_a | self.file_b, self.dir_a)):
            originals = {record.id: self.file_identity(record) for record in batch}
            with self.assertRaises(AccessError):
                self.as_user(batch).write({'directory_id': destination.id})
            for record in batch:
                self.assertEqual(self.file_identity(record), originals[record.id])

    def test_destination_post_write_denial_restores_original_content_and_location(self):
        original = self.file_identity(self.file_a)
        # Deliberately no caller savepoint: the implementation must undo its
        # own write when destination post-validation denies the operation.
        with self.assertRaises(AccessError):
            self.as_user(self.file_a).write({'directory_id': self.create_only_root.id})
        self.assertEqual(self.file_identity(self.file_a), original)


@tagged('post_install', '-at_install', 'baseer_dms_trial')
class TestDmsDestinationRpc(DestinationFixtures, HttpCase):
    def test_authenticated_move_rpc_denies_single_company_and_allows_authorized_both(self):
        self.editor.company_ids |= self.company_b
        self.authenticate(self.editor.login, 'trial')
        def move(companies):
            response = self.url_open(
                '/web/dataset/call_kw/dms.file/write',
                data=json.dumps({
                    'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                    'params': {
                        'model': 'dms.file', 'method': 'write',
                        'args': [self.file_a.ids, {'name': 'rpc-moved.txt', 'directory_id': self.dir_b.id}],
                        'kwargs': {'context': {'allowed_company_ids': companies}},
                    },
                }), headers={'Content-Type': 'application/json'},
            )
            self.assertEqual(response.status_code, 200)
            return response.json()
        denied = move(self.company_a.ids)
        self.assertIn('error', denied)
        self.assertEqual(denied['error']['data']['name'], 'odoo.exceptions.AccessError')
        self.file_a.invalidate_recordset()
        self.assertEqual(self.file_a.directory_id, self.dir_a)
        self.assertEqual(self.file_a.name, 'synthetic-contract.txt')
        self.assertEqual(self.file_a.content, self.payload)
        allowed = move((self.company_a | self.company_b).ids)
        self.assertNotIn('error', allowed, allowed)
        self.assertTrue(allowed['result'])
        self.file_a.invalidate_recordset()
        self.assertEqual(self.file_a.directory_id, self.dir_b)
        self.assertEqual(self.file_a.company_id, self.company_b)
        self.assertEqual(self.file_a.content, self.payload)


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
        partner = cls.env["res.partner"].create({"name": "Shared synthetic partner"})
        cls.unrelated_attachment = cls.env["ir.attachment"].create({
            "name": "unrelated.txt", "res_model": "res.partner", "res_id": partner.id,
            "datas": cls.payload,
        })


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
        self.assertEqual(self.attachment.with_user(self.owner).datas, self.payload)
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

    def test_guard_does_not_block_unrelated_attachment(self):
        ordinary = self.unrelated_attachment.with_user(self.manager)
        self.assertEqual(ordinary.datas, self.payload)
        # Same observable access with the new rule disabled, transaction only.
        self.env.ref("baseer_dms_trial.private_attachment").write({"active": False})
        ordinary.invalidate_recordset()
        self.assertEqual(ordinary.datas, self.payload)


@tagged("post_install", "-at_install", "baseer_dms_trial")
class TestDmsPrivateDownload(PrivateFixtures, HttpCase):
    def test_private_owner_download_allowed(self):
        # Isolated CI fixture only; never change credentials on QA.
        self.owner.write({"company_id": self.company_a.id, "password": "admin"})
        self.authenticate(self.owner.login, "admin")
        response = self.url_open(f"/my/dms/file/{self.file_a.id}/download")
        self.assertEqual(response.content, base64.b64decode(self.payload))
        self.assertFalse(self.file_a.access_token)

    def test_private_download_denied_even_for_manager(self):
        path = f"/my/dms/file/{self.file_a.id}/download"
        for login in (None, "dms-private-manager"):
            if login:
                self.authenticate(login, "trial")
            for suffix in ("", "?access_token=invalid-trial-token"):
                response = self.url_open(path + suffix)
                self.assertNotIn(base64.b64decode(self.payload), response.content)
            direct = self.url_open(f"/web/content/{self.attachment.id}?download=true")
            self.assertNotIn(base64.b64decode(self.payload), direct.content)
        self.assertFalse(self.file_a.access_token)
