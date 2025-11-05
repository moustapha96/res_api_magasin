import random
import string
from odoo import fields, models, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
import logging
from datetime import datetime, timedelta
import base64
_logger = logging.getLogger(__name__)


class Magasin(models.Model):
    _name = 'gestion.magasin'
    _description = 'Magasin'


    numero_etage = fields.Integer(string='Numéro d\'étage')
    numero_magasin = fields.Char(string='Numéro du magasin')
    account_move_ids = fields.One2many('account.move', 'magasin_id', string='Factures')

    
    name = fields.Char(required=True)
    code = fields.Char(string='Code', help='Code interne du magasin')
    partner_id = fields.Many2one('res.partner', string='Propriétaire', required=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', string='Société', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    # Coordonnées
    email = fields.Char()
    phone = fields.Char()
    city = fields.Char()
    adress = fields.Char(string='Adresse')

    # Géoloc / horaires
    latitude = fields.Float()
    longitude = fields.Float()
    opening_hours = fields.Char(string='Horaires')

    # Branding
    logo = fields.Binary(string='Logo (image_1920-like)')
    logo_filename = fields.Char()

    # Flag
    is_default = fields.Boolean(string='Magasin par défaut', default=False)

    _sql_constraints = [
        ('uniq_code_per_partner', 'unique(code, partner_id)', 'Ce code est déjà utilisé pour ce partenaire.'),
    ]

    @api.constrains('is_default', 'partner_id')
    def _ensure_single_default(self):
        for rec in self:
            if rec.is_default and rec.partner_id:
                others = self.search([('partner_id', '=', rec.partner_id.id), ('id', '!=', rec.id), ('is_default', '=', True)])
                if others:
                    others.write({'is_default': False})

    def set_as_default(self):
        for rec in self:
            rec.partner_id.magasin_ids.write({'is_default': False})
            rec.is_default = True

    def toggle_active(self):
        for rec in self:
            rec.active = not rec.active

    def send_sms (self, message , phone):
        sms_record = self.env['send.sms'].create({
                'recipient': phone,
                'message': message,
            }).send_sms()


