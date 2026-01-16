import random
import string
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
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

    # Flag pour savoir si on attend un mot de passe envoyé via WhatsApp
    waiting_password_whatsapp = fields.Boolean(
        string="En attente mot de passe (WhatsApp)",
        default=False,
        help="Indique si l'on attend que le client envoie son mot de passe via WhatsApp."
    )

    def generate_password(self, length=12):
        """Génère un mot de passe aléatoire sécurisé"""
        characters = string.ascii_letters + string.digits + "!@#$%&*"
        password = ''.join(random.choice(characters) for _ in range(length))
        return password

    def action_create_and_send_password(self):
        """Crée un mot de passe web et l'envoie par email"""
        self.ensure_one()
        
        if not self.email:
            raise ValidationError(_("L'adresse email est requise pour envoyer le mot de passe. Veuillez d'abord renseigner l'email du contact."))
        
        # Générer un nouveau mot de passe
        new_password = self.generate_password()
        
        # Sauvegarder le mot de passe dans le champ du contact
        self.write({'password': new_password})
        self.write({'is_verified': True})
        
        # Envoyer l'email avec le mot de passe (le template utilisera object.password)
        template = self.env.ref('res_api_magasin.email_template_send_password', raise_if_not_found=False)
        if template:
            try:
                template.send_mail(self.id, force_send=True)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Succès'),
                        'message': _('Le mot de passe a été généré et envoyé par email à %s') % self.email,
                        'type': 'success',
                        'sticky': False,
                    }
                }
            except Exception as e:
                _logger.exception("Erreur lors de l'envoi de l'email avec le mot de passe: %s", e)
                raise ValidationError(_("Erreur lors de l'envoi de l'email: %s") % str(e))
        else:
            # Fallback: envoi manuel si le template n'existe pas
            _logger.warning("Template email 'email_template_send_password' introuvable, envoi manuel")
            raise ValidationError(_("Le template d'email n'a pas été trouvé. Veuillez contacter l'administrateur."))

    def action_view_account_receivable(self):
        """Ouvre le compte comptable client"""
        self.ensure_one()
        account = self.property_account_receivable_id
        if not account:
            raise ValidationError(_("Aucun compte client n'est défini pour ce contact."))
        return {
            'name': _('Compte Client'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.account',
            'view_mode': 'form',
            'res_id': account.id,
            'target': 'current',
        }

    def action_view_account_payable(self):
        """Ouvre le compte comptable fournisseur"""
        self.ensure_one()
        account = self.property_account_payable_id
        if not account:
            raise ValidationError(_("Aucun compte fournisseur n'est défini pour ce contact."))
        return {
            'name': _('Compte Fournisseur'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.account',
            'view_mode': 'form',
            'res_id': account.id,
            'target': 'current',
        }
