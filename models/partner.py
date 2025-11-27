import random
import string
from odoo import fields, models, api, _
import logging
from datetime import datetime, timedelta
import base64
_logger = logging.getLogger(__name__)
class Partner(models.Model):
    _inherit = 'res.partner'

    password = fields.Char(string='Mot de passe de connexion sur la partie web',  required=False)
    is_verified = fields.Boolean(string='Etat verification compte mail', default=False)
    avatar = fields.Char(string='Photo profil Client', required=False)

    date_naissance = fields.Date(string='Date de Naissance',  required=False)
    lieu_naissance = fields.Char(string='Lieu de Naissance' , required=False)
    sexe = fields.Selection([('masculin', 'Masculin'), ('feminin', 'Feminin')], string='Sexe' , required=False)
    nationalite = fields.Char(string='Nationalite', required=False)

    # OTP
    otp_code = fields.Char(string='Code OTP', copy=False)
    otp_expiration = fields.Datetime(string='Expiration OTP', copy=False)

    
    


