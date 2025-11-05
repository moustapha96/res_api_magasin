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
        string="URL de paiement (Front)",
        required=True,
        default='https://dev.ccbmshop.com/facture-magasin',
        help="URL complète de la page front qui affiche/traite le paiement (ex: https://app.mondomaine.com/facture-magasin)"
    )

    active = fields.Boolean(default=True)

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
