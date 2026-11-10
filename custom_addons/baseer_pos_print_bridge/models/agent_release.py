import base64
import hashlib
import json
import re
import struct
from urllib.parse import urlparse

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .common import new_secret


class BaseerPrintAgentRelease(models.Model):
    """An immutable administrator-approved Windows agent download.

    The binary is intentionally owned by the existing print bridge rather than
    a second application: pairing, health, print jobs and release provenance
    all have the same operational owner.
    """

    _name = 'baseer.print.agent.release'
    _description = 'Baseer Print Agent Release'
    _order = 'approved_at desc, id desc'

    # The installer is served by the web server as a static file, outside the
    # Odoo process. Git stores source only: there is one deployed binary and
    # one atomic current-file switch, avoiding drift between mirrors.
    _PUBLIC_DOWNLOAD_URL = 'https://baseer.abroj.sa/downloads/Baseer.PrintAgent.exe'

    name = fields.Char(required=True, default='Baseer Print Agent')
    version = fields.Char(required=True, index=True)
    artifact = fields.Binary(attachment=True, groups='base.group_system')
    artifact_filename = fields.Char(required=True, groups='base.group_system')
    catalog_only = fields.Boolean(readonly=True, copy=False)
    artifact_sha256 = fields.Char(readonly=True, copy=False)
    release_notes = fields.Text()
    github_download_url = fields.Char(
        string='تنزيل تحديث جهاز مرتبط من GitHub',
        help='Downloads the general installer. It does not create a new pairing.',
    )
    signer_identity = fields.Char(help='Optional Authenticode publisher identity.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('retired', 'Retired'),
    ], required=True, default='draft', index=True)
    approved_at = fields.Datetime(readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)

    _version_unique = models.Constraint(
        'UNIQUE(version)', 'Each Windows agent version may be published only once.')

    _BOOTSTRAP_MAGIC = b'BASEER-BOOTSTRAP-V1'
    _BOOTSTRAP_MAX_BYTES = 4096

    def _require_system_admin(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only a system administrator can manage Windows agent releases.'))

    @api.constrains('version')
    def _check_version(self):
        for record in self:
            if not (record.version or '').strip() or len(record.version) > 64:
                raise ValidationError(_('Enter a valid agent version.'))

    @api.constrains('artifact_filename')
    def _check_artifact_filename(self):
        for record in self:
            filename = (record.artifact_filename or '').lower()
            if filename and not filename.endswith('.exe'):
                raise ValidationError(_('The Windows agent download must be an .exe installer.'))

    @api.constrains('github_download_url')
    def _check_github_download_url(self):
        for record in self.filtered('github_download_url'):
            parsed = urlparse(record.github_download_url)
            if (parsed.scheme != 'https' or parsed.netloc != 'github.com'
                    or not parsed.path.startswith('/hajrix01-star/abroj-baseer-production/releases/download/')
                    or parsed.query or parsed.fragment):
                raise ValidationError(_('Use a Baseer GitHub release download URL.'))

    def _artifact_bytes(self):
        self.ensure_one()
        try:
            return base64.b64decode(self.artifact or b'', validate=True)
        except (ValueError, TypeError) as error:
            raise ValidationError(_('The uploaded agent artifact is invalid.')) from error

    def action_approve(self):
        self._require_system_admin()
        for release in self:
            if release.state != 'draft':
                raise UserError(_('Only a draft release can be approved.'))
            payload = release._artifact_bytes()
            if not payload:
                raise ValidationError(_('Upload the Windows agent installer before approval.'))
            release.write({
                'state': 'approved',
                'artifact_sha256': hashlib.sha256(payload).hexdigest(),
                'approved_at': fields.Datetime.now(),
                'approved_by': self.env.user.id,
            })
        return True

    def action_retire(self):
        self._require_system_admin()
        approved = self.env['baseer.print.agent.release'].search([('state', '=', 'approved')])
        retiring = self.filtered(lambda release: release.state == 'approved')
        pairing_releases = approved.filtered(lambda release: not release.catalog_only)
        if retiring and (not (approved - retiring)
                         or (pairing_releases and not (pairing_releases - retiring))):
            raise UserError(_(
                'لا يمكن إيقاف آخر إصدار معتمد لوكيل الطباعة. '
                'ارفع واعتمد إصدارًا بديلاً أولًا، ليبقى التنزيل متاحًا للأجهزة الجديدة.'
            ))
        retiring.write({'state': 'retired'})
        return True

    @api.model
    def _approved_pairing_release(self):
        return self.search([('state', '=', 'approved'), ('catalog_only', '=', False)], limit=1)

    @api.model
    def _register_github_release(self, version, digest):
        """Import the version and digest pinned in reviewed module data."""
        if not self.env.su:
            raise AccessError(_('Only a trusted module upgrade can register this release.'))
        if not re.fullmatch(r'(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){2}', version):
            raise ValidationError(_('Enter a valid agent version.'))
        if not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValidationError(_('Enter a valid SHA-256 fingerprint.'))
        url = (
            'https://github.com/hajrix01-star/abroj-baseer-production/releases/download/'
            f'baseer-print-agent-{version}/Baseer.PrintAgent.exe'
        )
        version_key = tuple(map(int, version.split('.')))
        approved_catalog = self.search([('catalog_only', '=', True), ('state', '=', 'approved')])

        def catalog_version(record):
            return tuple(map(int, record.version.split('.')))

        release = self.search([('version', '=', version)], limit=1)
        if release:
            if release.artifact_sha256 != digest or release.github_download_url not in (False, url):
                raise ValidationError(_('The registered installer differs from the reviewed GitHub release.'))
            if release.state != 'approved':
                return
            if not release.github_download_url:
                release.write({'github_download_url': url})
        else:
            superseded = any(catalog_version(record) > version_key for record in approved_catalog)
            self.create({
                'version': version,
                'artifact_filename': 'Baseer.PrintAgent.exe',
                'artifact_sha256': digest,
                'github_download_url': url,
                'catalog_only': True,
                'state': 'retired' if superseded else 'approved',
                'approved_at': fields.Datetime.now(),
                'approved_by': self.env.user.id,
            })
        approved_catalog.filtered(lambda record: catalog_version(record) < version_key).action_retire()

    @api.model
    def auto_update_manifest(self):
        """Return only the most recently approved, externally hosted release.

        The agent still decides whether the version is newer.  Odoo is the
        approval authority; GitHub only hosts the immutable executable.
        """
        release = self.search([
            ('state', '=', 'approved'),
            ('github_download_url', '!=', False),
            ('artifact_sha256', '!=', False),
        ], order='approved_at desc, id desc', limit=1)
        if not release:
            return False
        return {
            'version': release.version,
            'download_url': release.github_download_url,
            'sha256': release.artifact_sha256,
        }

    def action_download(self):
        self.ensure_one()
        self._require_system_admin()
        if self.state != 'approved':
            raise UserError(_('Approve the release before downloading it.'))
        return {
            'type': 'ir.actions.act_url',
            'url': self.github_download_url or self._PUBLIC_DOWNLOAD_URL,
            'target': 'self',
        }

    def action_download_and_connect(self, agent):
        """Return a one-click download URL without persisting a raw secret.

        The controller creates the short-lived pairing secret immediately
        before streaming the approved executable.  The raw secret therefore
        exists only in that request and in the downloaded file's one-time
        bootstrap overlay; the database retains its HMAC fingerprint only.
        """
        self.ensure_one()
        self._require_system_admin()
        agent.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Approve the release before downloading it.'))
        if self.catalog_only:
            raise UserError(_('Select an approved release with a pairing installer.'))
        if (agent.state != 'new' or not agent.active
                or not agent.device_uid.startswith('PENDING-')):
            raise ValidationError(_('Create a new pending Windows print computer before downloading its connection file.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/baseer/print/agent-release/%s/download?bootstrap_agent_id=%s' % (self.id, agent.id),
            'target': 'self',
        }

    def action_download_and_connect_current_company(self):
        """Technical release entry with the same safe one-click behavior.

        This intentionally never exposes the legacy, unpaired installer: a
        release-center download remains usable for administrators, but always
        produces the same company-scoped connection file as the POS tab.
        """
        self.ensure_one()
        self._require_system_admin()
        if self.state != 'approved':
            raise UserError(_('Approve the release before downloading it.'))
        release = self._approved_pairing_release() if self.catalog_only else self
        if not release:
            raise UserError(_('Select an approved release with a pairing installer.'))
        company = self.env.company
        if company._baseer_effective_print_agent():
            raise UserError(_('A Windows print computer is already active for this company. Use its repair action instead.'))
        Agent = self.env['baseer.print.agent']
        pending = Agent.search([
            ('active', '=', True),
            ('state', '=', 'new'),
            ('device_uid', '=like', 'PENDING-%'),
            ('allowed_company_ids', 'in', company.ids),
        ], order='id desc', limit=1)
        if not pending:
            pending = Agent.create({
                'name': _('New printer computer'),
                'device_uid': 'PENDING-%s' % new_secret(24),
                'allowed_company_ids': [Command.set(company.ids)],
            })
        return release.action_download_and_connect(pending)

    def _bootstrap_artifact(self, server_url, pairing_code):
        """Attach only a bounded, one-time HTTPS pairing envelope to an EXE."""
        self.ensure_one()
        parsed = urlparse(server_url or '')
        if parsed.scheme != 'https' or not parsed.netloc:
            raise ValidationError(_('This environment has no HTTPS address for secure agent pairing.'))
        # The shipped 1.5.11 Agent deserializes with System.Text.Json's
        # default case-sensitive options.  These names must therefore match
        # its ServerUrl and PairingCode properties byte-for-byte; snake_case
        # and camelCase silently open the manual pairing window instead.
        envelope = json.dumps({
            'ServerUrl': server_url.rstrip('/'),
            'PairingCode': pairing_code,
        }, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
        if not envelope or len(envelope) > self._BOOTSTRAP_MAX_BYTES:
            raise ValidationError(_('The Windows agent connection envelope is invalid.'))
        return self._artifact_bytes() + envelope + struct.pack('<I', len(envelope)) + self._BOOTSTRAP_MAGIC

    def write(self, vals):
        self._require_system_admin()
        immutable = {'version', 'artifact', 'artifact_filename', 'artifact_sha256', 'signer_identity', 'catalog_only'}
        if 'github_download_url' in vals and self.filtered('catalog_only'):
            raise UserError(_('A reviewed GitHub release URL is immutable.'))
        if immutable.intersection(vals) and self.filtered(lambda release: release.state != 'draft'):
            raise UserError(_('An approved agent release is immutable. Publish a new version instead.'))
        if 'state' in vals and vals['state'] == 'draft' and self.filtered(lambda release: release.state != 'draft'):
            raise UserError(_('An approved or retired release cannot return to draft.'))
        return super().write(vals)

    def unlink(self):
        self._require_system_admin()
        if self.filtered(lambda release: release.state != 'draft'):
            raise UserError(_('Approved agent releases are retained for audit and rollback.'))
        return super().unlink()
