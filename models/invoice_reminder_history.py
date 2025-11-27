# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class InvoiceReminderHistory(models.Model):
    _name = 'invoice.reminder.history'
    _description = 'Historique des rappels de factures (SMS et Email)'
    _order = 'send_date desc'
    _rec_name = 'display_name'

    invoice_id = fields.Many2one(
        'account.move',
        string='Facture',
        required=True,
        ondelete='cascade',
        index=True
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Client',
        related='invoice_id.partner_id',
        store=True,
        readonly=True
    )
    
    reminder_type = fields.Selection(
        [
            ('sms', 'SMS'),
            ('email', 'Email'),
        ],
        string='Type de rappel',
        required=True,
        index=True
    )
    
    recipient = fields.Char(
        string='Destinataire',
        required=True,
        help="Numéro de téléphone pour SMS ou adresse email pour Email"
    )
    
    status = fields.Selection(
        [
            ('sent', 'Envoyé'),
            ('failed', 'Échec'),
            ('pending', 'En attente'),
        ],
        string='Statut',
        required=True,
        default='pending',
        index=True
    )
    
    send_date = fields.Datetime(
        string='Date d\'envoi',
        required=True,
        default=fields.Datetime.now,
        index=True
    )
    
    error_message = fields.Text(
        string='Message d\'erreur',
        help="Message d'erreur en cas d'échec d'envoi"
    )
    
    message_content = fields.Text(
        string='Contenu du message',
        help="Contenu du SMS ou sujet de l'email"
    )
    
    mail_id = fields.Many2one(
        'mail.mail',
        string='Email Odoo',
        help="Référence à l'enregistrement mail.mail si c'est un email"
    )
    
    is_automatic = fields.Boolean(
        string='Envoi automatique',
        default=True,
        help="Indique si l'envoi a été effectué automatiquement par le cron"
    )
    
    display_name = fields.Char(
        string='Nom',
        compute='_compute_display_name',
        store=True
    )
    
    @api.depends('invoice_id', 'reminder_type', 'send_date', 'status')
    def _compute_display_name(self):
        for record in self:
            invoice_name = record.invoice_id.name if record.invoice_id else 'N/A'
            type_label = dict(record._fields['reminder_type'].selection).get(record.reminder_type, '')
            status_label = dict(record._fields['status'].selection).get(record.status, '')
            record.display_name = f"{invoice_name} - {type_label} - {status_label}"

    @api.model
    def create_history_record(self, invoice_id, reminder_type, recipient, status='sent', 
                             error_message=None, message_content=None, mail_id=None, is_automatic=True):
        """
        Méthode utilitaire pour créer un enregistrement d'historique.
        
        :param invoice_id: ID de la facture
        :param reminder_type: 'sms' ou 'email'
        :param recipient: Numéro de téléphone ou adresse email
        :param status: 'sent', 'failed', ou 'pending'
        :param error_message: Message d'erreur si échec
        :param message_content: Contenu du message
        :param mail_id: ID du mail.mail si c'est un email
        :param is_automatic: True si envoi automatique
        :return: L'enregistrement créé
        """
        return self.create({
            'invoice_id': invoice_id,
            'reminder_type': reminder_type,
            'recipient': recipient,
            'status': status,
            'error_message': error_message,
            'message_content': message_content,
            'mail_id': mail_id,
            'is_automatic': is_automatic,
        })

