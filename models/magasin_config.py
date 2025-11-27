# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class GestionMagasinConfig(models.Model):
    _name = 'gestion.magasin.config'
    _description = 'Configuration Front Paiement (Rental)'
    _rec_name = 'name'

    name = fields.Char(
        string='Nom de la Configuration',
        required=True,
        help="Nom descriptif pour cette configuration"
    )

    frontend_url = fields.Char(
        string="URL Frontend",
        required=True,
        default='https://portail.toubasandaga.sn',
        help="URL frontend (ex: https://app.mondomaine.com/facture-magasin)"
    )

    frontend_url_facture = fields.Char(
        string="URL de paiement (Front)",
        required=True,
        default='https://portail.toubasandaga.sn/facture-magasin',
        help="URL complète de la page front qui affiche/traite le paiement (ex: https://app.mondomaine.com/facture-magasin)"
    )

    active = fields.Boolean(default=True)

    enable_automatic_reminders = fields.Boolean(
        string="Activer les rappels automatiques",
        default=True,
        help="Si activé, le système enverra automatiquement des SMS et emails de rappel pour les factures à terme avec un montant restant à payer"
    )

    def get_frontend_url(self):
        """Retourne l'URL de paiement front (sélectionne l’enregistrement courant)."""
        self.ensure_one()
        if not self.frontend_url:
            raise ValidationError(_("Veuillez renseigner l'URL de paiement front."))
        return self.frontend_url

    @api.model
    def get_active_frontend_url(self):
        """Utilitaire: récupère l'URL depuis la config active, sinon None."""
        rec = self.search([('active', '=', True)], limit=1)
        return rec.frontend_url if rec and rec.frontend_url else None

    @api.model
    def is_automatic_reminders_enabled(self):
        """Vérifie si les rappels automatiques sont activés dans la configuration active."""
        config = self.search([('active', '=', True)], limit=1)
        if config:
            return config.enable_automatic_reminders
        return False
