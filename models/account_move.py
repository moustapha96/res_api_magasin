
# models/account_move.py
# -*- coding: utf-8 -*-
from odoo import models, fields, api, _ , http
from odoo.exceptions import ValidationError
import logging
import uuid
import requests 
from odoo.http import request, Response
import json


_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ---- Paiement en ligne ----
    transaction_id = fields.Char(string="ID de transaction", readonly=True, copy=False)
    payment_link = fields.Char(string="Lien de paiement", help="URL publique pour régler la facture")

    # ---- Contexte Rental ----
    rental_contract_id = fields.Many2one('rental.contract', string='Contrat de location', ondelete='set null')
    rental_property_id = fields.Many2one('rental.property', string='Local (propriété)', ondelete='set null')

    payment_link_wave = fields.Char(string="Lien de paiement Wave", help="URL publique pour régler la facture")

    payment_link_orange_money = fields.Char(string="Lien de paiement Orange Money", help="URL publique pour régler la facture")

    # ------------------------------------------------------------------
    # CREATE / WRITE
    # ------------------------------------------------------------------
    @api.model
    def create(self, vals):
        res = super().create(vals)
        if vals.get('move_type') == 'out_invoice':
            tid = vals.get('transaction_id') or str(uuid.uuid4())
            res.write({'transaction_id': tid})
            base_url = res._compute_frontend_url()
            res.write({'payment_link': f"{base_url}?transaction={tid}"})
        return res

    

    def write(self, vals):
        for inv in self:
            if 'transaction_id' in vals:
                base_url = inv._compute_frontend_url()
                vals['payment_link'] = f"{base_url}?transaction={vals['transaction_id']}"
            elif not inv.transaction_id and inv.move_type == 'out_invoice':
                tid = str(uuid.uuid4())
                vals['transaction_id'] = tid
                base_url = inv._compute_frontend_url()
                vals['payment_link'] = f"{base_url}?transaction={tid}"
        return super().write(vals)

    # ------------------------------------------------------------------
    # UTILS
    # ------------------------------------------------------------------
    def _get_frontend_url(self):
        """
        Lit l'URL publique depuis ir.config_parameter:
          - clé: rental.frontend_payment_url
        Exemple de valeur: https://app.mondomaine.com/facture-rental
        """
        icp = self.env['ir.config_parameter'].sudo()
        url = icp.get_param('rental.frontend_payment_url')
        if not url:
            raise ValidationError(_("Veuillez configurer la clé système 'rental.frontend_payment_url' (URL de paiement)."))
        return url


    def _compute_frontend_url(self):
        # 1) config model
        cfg = self.env['gestion.magasin.config'].sudo().search([('active', '=', True)], limit=1)
        if cfg and cfg.frontend_url:
            return cfg.frontend_url
        # 2) fallback ICP
        icp = self.env['ir.config_parameter'].sudo()
        icp_url = icp.get_param('rental.frontend_payment_url')
        if icp_url:
            return icp_url
        # Aucun des deux configuré
        raise ValidationError(_("Aucune URL front de paiement n’est configurée. "
                                "Créez une configuration (menu: Rental > Configuration > Paiement (Front)) "
                                "ou définissez le paramètre système 'rental.frontend_payment_url'."))

    def generate_invoice_link(self):
        self.ensure_one()
        base = self._compute_frontend_url()
        return f"{base}?transaction={self.transaction_id}" if self.transaction_id else base

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def action_generate_payment_link(self):
        self.ensure_one()
        tid = str(uuid.uuid4())
        self.write({
            'transaction_id': tid,
            'payment_link': f"{self._compute_frontend_url()}?transaction={tid}",
        })
        msg, t = _("Le lien de paiement a été généré pour la facture %s.") % self.name, 'success'
        self.send_payment_link_sms_with_details()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _("Lien de paiement"), 'message': msg, 'type': t, 'sticky': False}
        }

    def action_register_partner_payment(self):
        """
        Encaissement manuel du reste à payer (journal bancaire de la société).
        """
        self.ensure_one()
        if self.payment_state == 'paid':
            raise ValidationError(_("Cette facture est déjà soldée."))

        bank_journal = self.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', self.company_id.id)],
            limit=1
        )
        if not bank_journal:
            raise ValidationError(_("Aucun journal bancaire trouvé pour l'encaissement."))

        pay = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_id.id,
            'amount': self.amount_residual,
            'payment_method_id': self.env.ref('account.account_payment_method_manual_in').id,
            'journal_id': bank_journal.id,
            # 'payment_date': fields.Date.context_today(self),
            # 'communication': _("Règlement facture %s") % (self.name),
        })
        pay.action_post()

        # Affectation automatique si possible
        for line in pay.line_ids:
            if line.account_id.internal_type in ('receivable', 'payable'):
                try:
                    self.js_assign_outstanding_line(line.id)
                except Exception as e:
                    _logger.warning("Affectation automatique du paiement impossible: %s", e)
        return True

   
    def send_payment_link_sms_with_details(self):
        """
        Envoie un SMS avec :
        - Le montant restant à payer.
        - Le nom du magasin (si disponible).
        - La signature "Touba Sandaga".
        """
        self.ensure_one()

        # 1. Vérifier le numéro de téléphone
        phone = self.partner_id.mobile or self.partner_id.phone
        if not phone:
            raise ValidationError(_("Aucun numéro de téléphone n'est renseigné pour le partenaire %s.") % self.partner_id.display_name)

        # 2. Vérifier le lien de paiement
        if not self.payment_link:
            raise ValidationError(_("Aucun lien de paiement n'est associé à cette facture."))

        # 3. Récupérer le nom du magasin (si disponible)
        magasin_name = ""
        if hasattr(self, 'rental_property_id') and self.rental_property_id:
            magasin_name = self.rental_property_id.name
        elif hasattr(self, 'rental_contract_id') and self.rental_contract_id and self.rental_contract_id.property_id:
            magasin_name = self.rental_contract_id.property_id.name

        # 4. Préparer le message SMS
        message = _("Bonjour %(partner)s,\n"
                    "Il vous reste %(amount)s à payer pour la facture %(invoice)s.\n"
                    "%(magasin)s\n"
                    "Lien de paiement : %(link)s\n"
                    "\n"
                    "Touba Sandaga") % {
            'partner': self.partner_id.name,
            'amount': f"{self.amount_residual} {self.currency_id.symbol}",
            'invoice': self.name,
            'magasin': f"Magasin : {magasin_name}" if magasin_name else "Magasin : Non spécifié",
            'link': self.payment_link,
        }

        # 5. Créer et envoyer le SMS
        sms = self.env['send.sms'].create({
            'recipient': phone,
            'message': message,
        })
        sms.send_sms()

        # 6. Logger l'envoi
        _logger.info("[SMS RENTAL] SMS envoyé à %s : %s", phone, message)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("SMS envoyé"),
                'message': _("SMS envoyé à %(phone)s avec le lien de paiement.") % {'phone': phone},
                'type': 'success',
            }
        }


    # ------------------------------------------------------------------
    # PAYLOAD (pour API / front)
    # ------------------------------------------------------------------
    def get_payment_details(self):
        """
        Retourne un dict exploitable sur le front:
        - infos facture (rental-friendly)
        - lignes
        - liens Rental (contrat/local)
        """
        self.ensure_one()
        if not self.payment_link:
            raise ValidationError(_("Aucun lien de paiement n'est associé à cette facture."))

        line_items = [{
            'id': l.id,
            'name': l.name,
            'quantity': l.quantity,
            'price_unit': l.price_unit,
            'price_subtotal': l.price_subtotal,
            'account': l.account_id.name
        } for l in self.invoice_line_ids]

        return {
            'id': self.id,
            'code': self.name,
            'move_type': self.move_type,
            'status': self.payment_state,             # ex: 'not_paid', 'paid', 'partial'
            'issue_date': self.invoice_date and self.invoice_date.isoformat(),
            'due_date': self.invoice_date_due and self.invoice_date_due.isoformat(),
            'currency': self.currency_id.name,
            'amount_total': self.amount_total,
            'amount_paid': self.amount_total - self.amount_residual,
            'amount_residual': self.amount_residual,
            'partner_id': self.partner_id.id,
            'partner_name': self.partner_id.display_name,
            'transaction_id': self.transaction_id,
            'payment_link': self.payment_link,
            'invoice_lines': [{
                'name': l.name,
                'quantity': l.quantity,
                'price_unit': l.price_unit,
                'subtotal': l.price_subtotal
            } for l in self.invoice_line_ids],
            # Contexte Rental
            'rental_contract_id': self.rental_contract_id.id if self.rental_contract_id else None,
            'rental_property_id': self.rental_property_id.id if self.rental_property_id else None,
        }

    # ------------------------------------------------------------------
    # (Option) Ouverture liste des locaux du partenaire (version Rental)
    # ------------------------------------------------------------------
    def action_view_partner_properties(self):
        """
        Smart-button: ouvrir les locaux liés au partenaire (locataire courant).
        """
        self.ensure_one()
        partner_id = self.partner_id.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Locaux du locataire'),
            'res_model': 'rental.property',
            'view_mode': 'tree,form',
            'domain': ['|', ('current_tenant_id', '=', partner_id), ('current_contract_id.tenant_id', '=', partner_id)],
            'context': {'search_default_current_tenant': partner_id},
        }
    

    def generate_wave_payment_link(self):
        """
        Appelle l'API Wave pour générer un lien de paiement,
        puis stocke le lien dans le champ `payment_link` de la facture.
        """
        self.ensure_one()

        # 1. Vérifier que la facture est une facture client non payée
        if self.move_type != 'out_invoice' or self.payment_state == 'paid':
            raise ValidationError(_("Cette facture ne peut pas être payée en ligne (déjà payée ou type incorrect)."))

        # 2. Récupérer la configuration Wave active
        config = self.env['wave.config'].sudo().search([('is_active', '=', True)], limit=1)
        if not config:
            raise ValidationError(_("Aucune configuration Wave active trouvée."))

        # 3. Préparer les données pour l'API Wave
        payload = {
            "amount": int(self.amount_residual),  # Montant restant à payer
            "currency": self.currency_id.name,    # Devise de la facture
            "success_url": f"https://portail.toubasandaga.sn/wave-paiement?transaction={self.transaction_id}",
            "error_url": config.callback_url,
        }

        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }

        try:
            # 4. Appeler l'API Wave pour créer une session de paiement
            response = requests.post(
                "https://api.wave.com/v1/checkout/sessions",
                json=payload,
                headers=headers,
                timeout=30
            )
            reference = f"{self.name}_{uuid.uuid4().hex[:8].upper()}"
            description = _("Paiement de la facture %s en ligne via Wave.") % self.name
            
            if response.status_code in [200, 201]:
                data = response.json()
                payment_url_wave = data.get('wave_launch_url') or data.get('checkout_url')
                wave_transaction = request.env['wave.transaction'].sudo().create({
                    'wave_id': data.get('id'),
                    'transaction_id': self.transaction_id,
                    'amount': int(self.amount_residual),
                    'currency': self.currency_id.name,
                    'status': 'pending',
                    'phone': self.partner_id.mobile or self.partner_id.phone,
                    'reference': reference,
                    'description': description,
                    'payment_link_url': data.get('wave_launch_url') or data.get('checkout_url'),
                    'wave_response': json.dumps(data),
                    'account_move_id': self.id,
                    'partner_id': self.partner_id.id,
                    'checkout_status': data.get('checkout_status'),
                    'payment_status': data.get('payment_status'),
                })
                if not payment_url_wave:
                    raise ValidationError(_("Aucun lien de paiement n'a été retourné par Wave."))

                # 5. Stocker le lien de paiement dans la facture
                self.write({
                    'payment_link_wave': payment_url_wave,
                })
                _logger.info(f"Lien de paiement Wave généré pour la facture {self.name}: {payment_url_wave}")
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Locaux du locataire'),
                    'res_model': 'rental.property',
                    'view_mode': 'tree,form',
                    
                }
                return payment_url_wave

            else:
                _logger.error(f"Erreur API Wave: {response.status_code} - {response.text}")
                raise ValidationError(_(f"Erreur lors de la création du paiement Wave: {response.text}"))

        except requests.exceptions.RequestException as e:
            _logger.error(f"Erreur de connexion à l'API Wave: {str(e)}")
            raise ValidationError(_(f"Erreur de connexion à Wave: {str(e)}"))

