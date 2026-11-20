"""Odoo owns kitchen presentation; Windows receives the existing raster envelope."""
import base64
import copy
import hashlib
import io
import logging
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation

from PIL import Image, ImageChops, UnidentifiedImageError

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import find_in_path

from .job import NATIVE_RECEIPT_MAX_BYTES, NATIVE_RECEIPT_MAX_PIXELS
from .note import normalize_detail_notes

MAX_HTML_BYTES = 128 * 1024
MAX_SOURCE_CHARACTERS = 30_000
MAX_SOURCE_LINES = 200
RENDER_TIMEOUT_SECONDS = 20
MAX_RENDER_BYTES = 4 * 1024 * 1024
_logger = logging.getLogger(__name__)


def _normalize_kitchen_jpeg_density(raw):
    # Qt writes 75 DPI into JFIF while producing already-sized printer pixels.
    # Older Windows agents otherwise scale them into their 96-DPI bitmap. Change
    # only the JFIF density, not JPEG coefficients, dimensions, or image data.
    if (len(raw) < 20 or raw[:4] != b'\xff\xd8\xff\xe0'
            or raw[4:6] < b'\x00\x10' or raw[6:11] != b'JFIF\x00'):
        raise ValidationError(_('The kitchen image has an unsupported JPEG header.'))
    return raw[:13] + b'\x01\x00\x60\x00\x60' + raw[18:]


class BaseerKitchenDocument(models.Model):
    _inherit = 'baseer.print.job'

    print_html = fields.Text(readonly=True, copy=False, groups='base.group_system')

    @api.model
    def _create_once(self, vals):
        job = super()._create_once(vals)
        if job.ticket_type == 'preparation' and not job.print_html and not job.receipt_image_sha256:
            job._freeze_kitchen_document()
        return job

    def _kitchen_document_values(self):
        self.ensure_one()
        payload = copy.deepcopy(self.payload)
        lines = payload.get('lines', [])
        if not isinstance(lines, list) or len(lines) > MAX_SOURCE_LINES:
            raise ValidationError(_('The kitchen document has too many lines.'))
        # Bound input before asking Qt to lay out an automatically sized document.
        if len(str(payload)) > MAX_SOURCE_CHARACTERS:
            raise ValidationError(_('The kitchen document is too large to render safely.'))

        def number(line, key):
            try:
                value = Decimal(str(line.get(key, 0)))
            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError(_('The kitchen quantity is invalid.')) from None
            if (not value.is_finite() or abs(value) > Decimal('1000000000')
                    or not -100 <= value.as_tuple().exponent <= 100):
                raise ValidationError(_('The kitchen quantity is invalid.'))
            return value

        def formatted(value):
            # Display the authoritative snapshot without recalculating intent.
            # Match the former kitchen renderer's 0.### display, including
            # harmless native float deltas such as 1.3 - 1.2. Never alter the event.
            return format(value, '.3f').rstrip('0').rstrip('.') or '0'

        actions = []
        for index, source in enumerate(lines):
            line = normalize_detail_notes(source)
            action = str(line.get('action', 'new')).lower()
            quantity = number(line, 'quantity')
            delta = number(line, 'delta_quantity')
            previous = number(line, 'previous_quantity')
            if action == 'update':
                action = 'reduce' if delta < 0 else 'add' if delta > 0 else 'update'
            if action not in ('new', 'add', 'reduce', 'cancel', 'update'):
                action = 'new'
            actions.append(action)
            qty = {
                'new': '+' + formatted(quantity),
                'add': '+' + formatted(abs(delta)),
                'reduce': '-' + formatted(abs(delta)),
                'cancel': '×' + formatted(previous if previous else abs(delta)),
            }.get(action, formatted(quantity))
            labels = {'new': 'جديد / NEW', 'add': 'إضافة / ADD',
                      'reduce': 'تخفيض / REDUCE', 'cancel': 'إلغاء / CANCEL',
                      'update': 'تعديل / UPDATE'}
            line.update({
                'quantity_label': qty,
                'action_label': labels[action],
                'quantity_total_label': (
                    ('الإجمالي / Total: ' if action == 'add' else 'المتبقي / Remaining: ')
                    + formatted(quantity) if action in ('add', 'reduce') else ''
                ),
            })
            lines[index] = line
        cancelled = bool(payload.get('cancellation')) or bool(actions) and all(a == 'cancel' for a in actions)
        changed = any(a in ('add', 'reduce', 'cancel', 'update') for a in actions)
        title = 'إلغاء الطلب / CANCEL' if cancelled else (
            'تغييرات المطبخ / KITCHEN CHANGES' if changed else 'طلب مطبخ جديد / NEW KITCHEN ORDER'
        )
        order = payload.get('order', {})
        if order.get('created_at'):
            # Company timezone, frozen once. Never use the claiming agent's clock.
            company = self.company_id
            tz = company.partner_id.tz or 'Asia/Riyadh'
            order['created_at'] = fields.Datetime.context_timestamp(
                self.with_context(tz=tz), fields.Datetime.to_datetime(order['created_at']),
            ).strftime('%Y-%m-%d %H:%M:%S')
        return {
            'title': title, 'order': order, 'lines': lines,
            'cancellation': payload.get('cancellation') or {},
            'paper_pixels': 384 if str(payload.get('printer', {}).get('paper_width')) == '58' else 576,
        }

    def _freeze_kitchen_document(self):
        self.ensure_one()
        if self.print_html:
            return True
        try:
            with self.env.cr.savepoint():
                document = self._kitchen_document_values()
                html = str(self.env['ir.qweb']._render(
                    'baseer_pos_print_bridge.kitchen_document', {'document': document},
                ))
                if not html or len(html.encode()) > MAX_HTML_BYTES:
                    raise ValidationError(_('The kitchen document is too large to render safely.'))
                self.sudo().write({'print_html': html})
        except Exception as error:
            # A presentation failure must not roll back saved kitchen intent.
            _logger.warning('Kitchen document %s snapshot failed (%s)', self.id, type(error).__name__)
            self._kitchen_render_failed()
            return False
        return True

    def _kitchen_render_failed(self):
        self.sudo().write({
            'state': 'failed', 'completed_at': fields.Datetime.now(),
            'error_code': 'document_render_failed',
            'error_detail': _('Odoo could not prepare the kitchen image. Review the document and renderer before reprinting.'),
        })

    def _render_kitchen_jpeg(self):
        self.ensure_one()
        if not self.print_html or len(self.print_html.encode()) > MAX_HTML_BYTES:
            raise ValidationError(_('The frozen kitchen document is missing or too large.'))
        width = 384 if str(self.payload.get('printer', {}).get('paper_width')) == '58' else 576
        command = [find_in_path('wkhtmltoimage'), '--disable-local-file-access', '--disable-javascript',
                   '--quiet', '--width', str(width), '--disable-smart-width', '--height', '0',
                   '--format', 'jpg', '--quality', '90', '-', '-']
        # File-backed output avoids buffering an unbounded raster in the Odoo worker.
        with tempfile.TemporaryFile() as output:
            subprocess.run(command, input=self.print_html.encode(), stdout=output,
                           stderr=subprocess.DEVNULL, timeout=RENDER_TIMEOUT_SECONDS, check=True)
            output.seek(0)
            raw = output.read(MAX_RENDER_BYTES + 1)
        if len(raw) > MAX_RENDER_BYTES:
            raise ValidationError(_('The kitchen document is too large to render safely.'))
        if len(raw) <= NATIVE_RECEIPT_MAX_BYTES:
            return self._validated_native_receipt_image(base64.b64encode(raw).decode())
        # Long bilingual tickets can fit the pixel guard but exceed the wire
        # budget at Qt's default JPEG settings. Preserve every pixel and row;
        # kitchen artwork is monochrome, so grayscale compression loses no color.
        try:
            with Image.open(io.BytesIO(raw)) as picture:
                if (picture.format != 'JPEG' or picture.width != width
                        or not 1 <= picture.height <= 12000
                        or picture.width * picture.height > NATIVE_RECEIPT_MAX_PIXELS):
                    raise ValidationError(_('The kitchen document is too large to render safely.'))
                grayscale = picture.convert('L')
                try:
                    for quality in (90, 85, 80):
                        encoded = io.BytesIO()
                        grayscale.save(encoded, format='JPEG', quality=quality, optimize=True)
                        if encoded.tell() <= NATIVE_RECEIPT_MAX_BYTES:
                            return self._validated_native_receipt_image(
                                base64.b64encode(encoded.getvalue()).decode(),
                            )
                    # Thermal output is binary. For dense long text, encode the
                    # same 170-threshold used by the installed Windows renderer.
                    # Accept only candidates retaining EVERY original ink pixel
                    # and adding at most 2% ink; no resizing or discarded rows.
                    with grayscale.point(lambda tone: 0 if tone < 170 else 255) as binary:
                        ink = binary.histogram()[0]
                        for quality in (65, 50, 40, 30, 25, 20):
                            encoded = io.BytesIO()
                            binary.save(encoded, format='JPEG', quality=quality, optimize=True)
                            if encoded.tell() > NATIVE_RECEIPT_MAX_BYTES:
                                continue
                            with Image.open(io.BytesIO(encoded.getvalue())) as candidate:
                                with candidate.point(lambda tone: 0 if tone < 170 else 255) as restored:
                                    with ImageChops.subtract(restored, binary) as lost:
                                        if lost.getbbox():
                                            continue
                                    with ImageChops.subtract(binary, restored) as added:
                                        if added.histogram()[255] * 100 > max(ink, 1) * 2:
                                            continue
                            return self._validated_native_receipt_image(
                                base64.b64encode(encoded.getvalue()).decode(),
                            )
                finally:
                    grayscale.close()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValidationError(_('The frozen kitchen document is missing or too large.')) from None
        raise ValidationError(_('The kitchen document is too large to render safely.'))

    def _ensure_kitchen_image(self):
        self.ensure_one()
        if self.receipt_image_sha256:
            # Never recreate a lost/purged original with a new raster or template.
            return True
        if not self._freeze_kitchen_document():
            return False
        try:
            raw, width, height, digest = self._render_kitchen_jpeg()
            raw = _normalize_kitchen_jpeg_density(raw)
            digest = hashlib.sha256(raw).hexdigest()
        except (OSError, subprocess.SubprocessError, ValidationError) as error:
            _logger.warning('Kitchen document %s raster failed (%s)', self.id, type(error).__name__)
            self._kitchen_render_failed()
            return False
        payload = dict(self.payload, receipt_image={
            'sha256': digest, 'width': width, 'height': height, 'format': 'jpeg',
        })
        self.sudo().with_context(image_no_postprocess=True).write({
            'receipt_image': base64.b64encode(raw), 'receipt_image_sha256': digest, 'payload': payload,
        })
        return True
